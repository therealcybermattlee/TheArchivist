"""Integration: a narrow pull must not cost the routine refresh its ground (005 US1).

The whole point of refusing to advance on a NARROW run is that the owed
interval survives. This is the end-to-end form of that promise.
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
ORIGINAL = "2026-08-26T20:00:00"


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run(conf, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args])


@pytest.mark.parametrize("narrow", [
    ["--recent", "50"],
    ["--until-found", "10"],
    ["--since", "2026-09-20", "--until", "2026-09-25"],
])
def test_no_narrow_form_moves_the_watermark(conf, cfg, monkeypatch, narrow):
    seed_source(cfg, "acct-a", pull_state=ORIGINAL, reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf, "--apply", *narrow)
    assert read_meta(cfg, "pull_state:acct-a") == ORIGINAL


def test_routine_refresh_after_a_narrow_pull_asks_for_the_whole_span(
        conf, cfg, monkeypatch):
    """The 2026-09-26 regression test, end to end.

    Under the old code the narrow pull advanced the watermark to the present
    and the routine refresh that followed asked only for the last seven days,
    orphaning everything between.
    """
    seed_source(cfg, "acct-a", pull_state=ORIGINAL, reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf, "--apply", "--recent", "50")

    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    run(conf, "--apply")
    assert calls[0]["since"] == "2026-08-19"      # ORIGINAL − 7-day overlap


def test_a_narrow_pull_still_does_its_work(conf, cfg, monkeypatch):
    """Refusing to advance is not refusing to pull."""
    seed_source(cfg, "acct-a", pull_state=ORIGINAL, reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    result = run(conf, "--apply", "--recent", "50")
    assert calls and calls[0]["recent"] == 50
    assert result.exit_code == 0                  # PARTIAL is not a failure
