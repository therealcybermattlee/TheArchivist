"""Safety test: no constructed argument list can ever mutate iCloud (005 case 22).

Constitution Principle I — Source Data Is Sacred. Nothing is ever deleted from
a cloud account, in any mode, under any flag combination. This test exists so
that adding a flag to build_download_cmd cannot quietly introduce one.
"""

from pathlib import Path

import pytest

from archivist.icloud import build_download_cmd, build_enumerate_cmd

#: Every icloudpd flag that can modify or delete from the iCloud account.
FORBIDDEN = ("--auto-delete", "--delete-after-download", "--keep-icloud-recent-days")

MODES = [
    dict(),                                          # routine unbounded
    dict(recent=500, since="2026-09-19"),            # routine bounded
    dict(since="2026-08-19"),                        # explicit since / reconcile
    dict(recent=50),                                 # narrow by count
    dict(until_found=10),                            # narrow by already-found
    dict(since="2020-01-01", until="2021-01-01"),    # historical slice
    dict(dry_run=True),                              # dry run
]


@pytest.mark.parametrize("kwargs", MODES)
def test_no_mutating_flag_in_any_mode(kwargs, tmp_path):
    cmd = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s",
                             **kwargs)
    for flag in FORBIDDEN:
        assert flag not in cmd, f"{flag} constructed for {kwargs}"


@pytest.mark.parametrize("kwargs", MODES)
def test_debug_logging_is_always_requested(kwargs, tmp_path):
    """The per-item skip lines are the evidence a bounded scan cleared its
    window. They are always captured; `verbose` decides only whether the
    OPERATOR sees them."""
    cmd = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s",
                             **kwargs)
    assert "--log-level" in cmd
    assert cmd[cmd.index("--log-level") + 1] == "debug"


def test_bounded_mode_passes_recent_and_the_date_filter(tmp_path):
    """FR-021: the date filter stays, so a pruned mirror does not re-fetch."""
    cmd = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s",
                             recent=500, since="2026-09-19")
    assert cmd[cmd.index("--recent") + 1] == "500"
    assert cmd[cmd.index("--skip-created-before") + 1] == "2026-09-19"


def test_reconcile_mode_passes_no_recent_bound(tmp_path):
    cmd = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s",
                             since="2026-08-19")
    assert "--recent" not in cmd


def test_dry_run_flag_is_passed_through(tmp_path):
    cmd = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s",
                             dry_run=True)
    assert "--dry-run" in cmd


# --- 006: the enumeration path is subject to the same prohibition ----------

def test_enumeration_can_never_mutate_the_source(tmp_path):
    """Listing is read-only by intent; this makes it read-only by test.

    Enumeration reaches the same account over the same credentials as a
    download, so it inherits Principle I in full. A flag added here must not
    be able to escape the prohibition just because this path transfers nothing.
    """
    cmd = build_enumerate_cmd("me@example.com", tmp_path / "m", tmp_path / "s")
    for flag in FORBIDDEN:
        assert flag not in cmd


def test_enumeration_requests_no_download(tmp_path):
    cmd = build_enumerate_cmd("me@example.com", tmp_path / "m", tmp_path / "s")
    assert "--only-print-filenames" in cmd


def test_enumeration_and_download_shape_paths_identically(tmp_path):
    """If these diverge, every listed item reads as missing.

    The comparison keys on the path the downloader WOULD write. Should the
    listing use a different folder structure or live-photo naming policy, no
    listed path could ever match a recorded one and the audit would report a
    100% gap on a complete archive.
    """
    enum = build_enumerate_cmd("me@example.com", tmp_path / "m", tmp_path / "s")
    dl = build_download_cmd("me@example.com", tmp_path / "m", tmp_path / "s")
    for flag in ("--folder-structure", "--size", "--live-photo-size",
                 "--live-photo-mov-filename-policy"):
        assert enum[enum.index(flag) + 1] == dl[dl.index(flag) + 1], flag
