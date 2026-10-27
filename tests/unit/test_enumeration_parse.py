"""Unit tests: `--only-print-filenames` output -> Listing (006).

Fixtures are derived from a real captured listing; see the fixtures README.
Three properties of that output are not documented upstream and are pinned
here because each one, got wrong, produces a silently wrong answer:

  1. there is NO completion sentence in this mode
  2. failures arrive on stdout, interleaved with items
  3. a printed path is not a unique asset key
"""

from pathlib import Path

import pytest

from archivist.icloud import Listing, build_enumerate_cmd, parse_enumeration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "icloudpd_streams"
MIRROR = Path("/work/staging/icloud/demo")


def stream(name: str) -> list[str]:
    return FIXTURES.joinpath(name).read_text(encoding="utf-8").splitlines()


def test_healthy_listing_is_complete():
    listing = parse_enumeration(stream("enumeration-sample.log"), mirror=MIRROR)
    assert listing.complete
    assert listing.notes == ()
    assert listing.paths


def test_paths_are_returned_relative_to_the_mirror():
    listing = parse_enumeration(stream("enumeration-sample.log"), mirror=MIRROR)
    assert all(not p.startswith("/") for p in listing.paths)
    assert any(p.endswith(".HEIC") for p in listing.paths)


def test_duplicate_target_paths_collapse():
    """6,100 real lines held 6,087 unique paths: two assets, one target path."""
    lines = stream("enumeration-sample.log")
    listing = parse_enumeration(lines, mirror=MIRROR)
    assert listing.listed_lines == len(lines)
    assert len(listing.paths) < listing.listed_lines


def test_truncated_listing_fails_closed():
    listing = parse_enumeration(stream("enumeration-truncated.log"),
                                mirror=MIRROR, truncated=True)
    assert not listing.complete
    assert any("mid-line" in n for n in listing.notes)


def test_error_on_stdout_fails_closed():
    """The dangerous one: failures share the stream with items.

    Three accounts wrote `Authentication required for Account. (421)` to
    STDOUT at --log-level error. A reader that assumed stdout held only paths
    would have read a 33,000-item library as holding one item.
    """
    listing = parse_enumeration(stream("enumeration-auth-error.log"), mirror=MIRROR)
    assert not listing.complete
    assert any("fresh sign-in" in n for n in listing.notes)
    # The valid paths before the error are parsed, but may not be acted on.
    assert listing.paths


def test_empty_library_is_complete_when_the_run_was():
    listing = parse_enumeration([], mirror=MIRROR)
    assert listing.complete
    assert listing.paths == frozenset()


def test_empty_listing_from_a_failed_run_is_not_complete():
    """"Zero items" and "could not list" must never collapse into one state."""
    listing = parse_enumeration([], mirror=MIRROR, exit_code=1)
    assert not listing.complete


def test_untested_version_fails_closed():
    listing = parse_enumeration([], mirror=MIRROR, version="9.9.9")
    assert not listing.complete
    assert any("not a version" in n for n in listing.notes)


def test_unusable_session_fails_closed_with_the_reason():
    listing = parse_enumeration([], mirror=MIRROR,
                                session_detail="sign-in never completed for x@y.z")
    assert not listing.complete
    assert any("never completed" in n for n in listing.notes)


@pytest.mark.parametrize("line,fragment", [
    ("2026-10-27 ERROR    Authentication required for Account. (421)", "fresh sign-in"),
    ("ERROR This Apple Account has been locked for security reasons.", "locked"),
    ("ERROR ('Invalid email/password combination.',)", "rejected the stored"),
    ("INFO     Two-factor authentication is required (2fa)", "two-factor"),
])
def test_each_failure_signal_is_named(line, fragment):
    listing = parse_enumeration([line], mirror=MIRROR)
    assert not listing.complete
    assert any(fragment in n for n in listing.notes), listing.notes


def test_unrecognised_error_still_fails_closed():
    listing = parse_enumeration(["2026-10-27 ERROR    something new went wrong"],
                                mirror=MIRROR)
    assert not listing.complete


# --- invocation safety -----------------------------------------------------

def test_enumeration_shapes_paths_exactly_like_a_download():
    """Divergence here makes every item read as missing, not a few."""
    enum = build_enumerate_cmd("me@example.com", MIRROR, Path("/s"))
    for flag, value in [("--folder-structure", "{:%Y/%m}"),
                        ("--size", "original"),
                        ("--live-photo-size", "original"),
                        ("--live-photo-mov-filename-policy", "original")]:
        assert enum[enum.index(flag) + 1] == value
    assert "--only-print-filenames" in enum


def test_enumeration_never_mutates_the_source():
    cmd = build_enumerate_cmd("me@example.com", MIRROR, Path("/s"))
    for forbidden in ("--auto-delete", "--delete-after-download"):
        assert forbidden not in cmd
