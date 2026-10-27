"""Integration: an undersized scan bound reports itself (005 US3, FR-023).

The failure mode this guards: a source busier than its bound would silently
skip whatever fell past the ceiling. Instead the run does real work, refuses to
over-claim, and names the setting to raise.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, WINDOW_NOT_CLEARED, fresh, mock_download,
                       read_meta, seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run(conf, *args):
    r = runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                            "--config", str(conf), *args])
    if r.exception and not isinstance(r.exception, SystemExit):
        raise r.exception
    return r


def test_bounded_scan_passes_recent_and_since(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply")
    assert calls[0]["recent"] == 500                  # enumeration is bounded
    assert calls[0]["since"] == "2026-09-13"          # and still date-filtered


def test_unfilled_window_holds_coverage_and_names_the_setting(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download",
                        mock_download([], proof=WINDOW_NOT_CLEARED))
    result = run(conf, "--apply")
    assert read_meta(cfg, "pull_state:acct-a") == "2026-09-20T08:00:00"
    assert "scan_bound" in result.output
    assert "coverage NOT advanced" in result.output


def test_unfilled_window_still_records_the_work_done(conf, cfg, monkeypatch):
    """Refusing to advance is not refusing to work — the run is still journaled."""
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download",
                        mock_download([], proof=WINDOW_NOT_CLEARED))
    run(conf, "--apply")
    rec = json.loads((list(cfg.logs_dir.glob("pull-*.jsonl"))[0]).read_text())
    assert rec["examined"] == 500
    assert rec["reached_before_cutoff"] is False
    assert rec["decision"] == "refuse"
    assert "scan_bound" in rec["reason"]


def test_next_run_re_covers_the_same_interval(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download",
                        mock_download([], proof=WINDOW_NOT_CLEARED))
    run(conf, "--apply")
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    run(conf, "--apply")
    assert calls[0]["since"] == "2026-09-13"          # unchanged: still owed


def test_configured_bound_is_used(fake_volumes, cfg, monkeypatch):
    conf = write_config(fake_volumes["tmp"], cfg,
                        {"acct-a": {**SOURCES["acct-a"], "scan_bound": 1500}})
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply")
    assert calls[0]["recent"] == 1500


def test_sweep_is_never_bounded(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh(40))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply")
    assert calls[0]["recent"] is None
