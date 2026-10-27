"""Integration: one source's sweep never contaminates another (005 FR-012)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, fresh, mock_download, read_meta,
                       seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {
    "acct-a": {"type": "icloud", "device_folder": "A Cell", "username": "a@example.com"},
    "acct-b": {"type": "icloud", "device_folder": "B Cell", "username": "b@example.com"},
    "acct-c": {"type": "icloud", "device_folder": "C Cell", "username": "c@example.com"},
}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def test_due_and_fresh_sources_take_different_paths_in_one_run(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    seed_source(cfg, "acct-c", pull_state=fresh(1), reconcile_state=fresh(99))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    runner.invoke(app, ["pull", "all", "--config", str(conf), "--apply"])
    modes = {c["username"]: c["recent"] for c in calls}
    assert modes == {"a@example.com": None, "b@example.com": 500,
                     "c@example.com": None}


def test_a_failing_sweep_leaves_other_sources_reconciled(conf, cfg, monkeypatch):
    for s in ("acct-a", "acct-b", "acct-c"):
        seed_source(cfg, s, pull_state=fresh(1), reconcile_state=fresh(40))
    monkeypatch.setattr(icloud, "download", mock_download(
        [], proof=COVERED, proof_for={"a@example.com": UNCONFIRMED}))
    runner.invoke(app, ["pull", "all", "--config", str(conf), "--apply"])
    assert read_meta(cfg, "reconcile_state:acct-a") is not None   # unchanged/stale
    for s in ("acct-b", "acct-c"):
        assert read_meta(cfg, f"reconcile_state:{s}") == read_meta(cfg, f"pull_state:{s}")


def test_per_source_journals_share_one_run_id(conf, cfg, monkeypatch):
    for s in ("acct-a", "acct-b", "acct-c"):
        seed_source(cfg, s, pull_state=fresh(1), reconcile_state=fresh(2))
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    runner.invoke(app, ["pull", "all", "--config", str(conf), "--apply"])
    journals = list(cfg.logs_dir.glob("pull-*.jsonl"))
    assert len(journals) == 1                       # one run, one journal
    assert len(journals[0].read_text().strip().splitlines()) == 3
