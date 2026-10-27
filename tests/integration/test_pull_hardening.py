"""Integration: hardening fixes from the 005 data-safety review (F2/F4/F6).

None of these were data-loss paths. F2 is a fail-OPEN in the one guard the
feature's own incident is about, which makes it worth closing even though no
tool-written state can currently reach it.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import COVERED, fresh, mock_download, read_meta, seed_source, write_config

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run(conf, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args])


# --- F2 --------------------------------------------------------------------

def test_unreadable_watermark_refuses_rather_than_falling_open(conf, cfg, monkeypatch):
    """A corrupt watermark must not be downgraded to "no watermark".

    Treating it as absent skips the --since span check, letting a later date
    overwrite it and permanently hide whatever span it was protecting.
    """
    seed_source(cfg, "acct-a", pull_state="not-a-timestamp", reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    result = run(conf, "--since", "2026-09-25", "--apply")
    assert read_meta(cfg, "pull_state:acct-a") == "not-a-timestamp"
    assert "unreadable" in result.output


# --- F4 --------------------------------------------------------------------

@pytest.mark.parametrize("flag,value", [
    ("--since", "2026-9-1"), ("--since", "yesterday"),
    ("--until", "09/25/2026"), ("--until", ""),
])
def test_malformed_dates_are_refused_before_anything_runs(conf, cfg, monkeypatch, flag, value):
    """A typo must not surface AFTER media has already been copied."""
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run(conf, flag, value, "--apply")
    assert result.exit_code == 2
    assert calls == []                       # refused before the download
    assert "YYYY-MM-DD" in (result.output + str(result.stderr or ""))


def test_well_formed_dates_are_accepted(conf, cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00", reconcile_state=fresh())
    result = run(conf, "--since", "2026-08-19", "--apply")
    assert result.exit_code == 0, result.output
    assert calls[0]["since"] == "2026-08-19"


# --- F6 --------------------------------------------------------------------

def test_full_plus_since_is_refused_not_silently_ignored(conf, cfg, monkeypatch):
    """A sweep drops the date filter, so honouring --full would discard --since.

    Ignoring a flag the operator typed is worse than refusing the combination:
    they asked for a bounded re-pull and would have got the whole library.
    """
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run(conf, "--full", "--since", "2026-08-19", "--apply")
    assert calls == []
    assert "contradictory" in result.output + str(result.stderr or "")
