"""Integration: windowed pull state through the CLI (004 FR-015, 005 US1).

icloud.download is mocked (no network); the state machinery, refusal paths and
advancement rules are exercised end-to-end through the typer app.

Amended by feature 005. Two cases in this file previously asserted the
behaviour that caused the 2026-09-26 coverage loss — a narrow `--recent N
--apply` advancing the watermark to the present — and now assert the opposite.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, fresh, mock_download, read_meta,
                       seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()

SOURCES = {
    "matt-personal": {"type": "icloud", "device_folder": "Matt Personal Cell",
                      "username": "test@example.com"},
}


@pytest.fixture
def icloud_config(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def invoke(config, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                               "--config", str(config), *args])


def test_stateless_bare_pull_refuses(icloud_config, monkeypatch):
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = invoke(icloud_config)
    assert result.exit_code != 0
    assert calls == []  # refused BEFORE any download
    out = result.output + getattr(result, "stderr", "")
    assert "--recent" in out and "--full" in out


def test_bare_pull_uses_stored_window(icloud_config, cfg, monkeypatch):
    seed_source(cfg, "matt-personal", pull_state="2026-07-31T12:00:00",
                reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = invoke(icloud_config)
    assert result.exit_code == 0, result.output
    assert calls[0]["since"] == "2026-07-24"  # last_pull − 7-day overlap


def test_dry_run_does_not_advance_state(icloud_config, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([]))
    result = invoke(icloud_config, "--recent", "5")
    assert result.exit_code == 0, result.output
    assert read_meta(cfg, "pull_state:matt-personal") is None


# --- 005: narrow pulls may no longer over-claim -----------------------------

def test_narrow_recent_pull_does_not_advance_state(icloud_config, cfg, monkeypatch):
    """REVERSED by 005. This used to advance the watermark to the present.

    A `--recent N` run fetches the N most recently ADDED items; it says nothing
    about the interval since the last watermark. Advancing on it silently
    orphaned everything in between — the defect that cost two sources a month
    of coverage on 2026-09-26.
    """
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = invoke(icloud_config, "--recent", "5", "--apply")
    assert calls and calls[0]["recent"] == 5      # the pull still happened
    assert read_meta(cfg, "pull_state:matt-personal") is None
    assert "coverage NOT advanced" in result.output


def test_narrow_until_found_pull_does_not_advance_state(icloud_config, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([]))
    invoke(icloud_config, "--until-found", "10", "--apply")
    assert read_meta(cfg, "pull_state:matt-personal") is None


def test_historical_range_slice_never_advances_state(icloud_config, cfg, monkeypatch):
    """A --since/--until slice is historical backfill — coverage must not move."""
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = invoke(icloud_config, "--since", "2013-01-01", "--until",
                    "2014-01-07", "--apply")
    assert calls[0]["since"] == "2013-01-01" and calls[0]["until"] == "2014-01-07"
    assert read_meta(cfg, "pull_state:matt-personal") is None


def test_narrow_pull_then_routine_refresh_still_covers_the_gap(
        icloud_config, cfg, monkeypatch):
    """The point of refusing: the owed interval must survive a narrow pull."""
    seed_source(cfg, "matt-personal", pull_state="2026-07-31T12:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([]))
    invoke(icloud_config, "--recent", "5", "--apply")

    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    invoke(icloud_config)
    assert calls[0]["since"] == "2026-07-24"      # still asking for the whole span


# --- 005: an unconfirmed download never advances ---------------------------

def test_unconfirmed_download_does_not_advance_state(icloud_config, cfg, monkeypatch):
    """The 2026-09-26 shape: reported success, fetched nothing, no signal."""
    seed_source(cfg, "matt-personal", pull_state="2026-07-31T12:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=UNCONFIRMED))
    result = invoke(icloud_config, "--apply")
    assert result.exit_code != 0
    assert read_meta(cfg, "pull_state:matt-personal") == "2026-07-31T12:00:00"
    assert "could not be confirmed" in result.output


def test_explicit_since_before_watermark_advances(icloud_config, cfg, monkeypatch):
    """`--since` is the repair tool for a known gap, so it may advance."""
    seed_source(cfg, "matt-personal", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    result = invoke(icloud_config, "--since", "2026-08-19", "--apply")
    assert result.exit_code == 0, result.output
    assert read_meta(cfg, "pull_state:matt-personal") != "2026-09-20T08:00:00"


def test_explicit_since_after_watermark_refuses(icloud_config, cfg, monkeypatch):
    """A later --since would silently skip the span between."""
    seed_source(cfg, "matt-personal", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    result = invoke(icloud_config, "--since", "2026-09-25", "--apply")
    assert read_meta(cfg, "pull_state:matt-personal") == "2026-09-20T08:00:00"
    assert "2026-09-20..2026-09-25" in result.output
