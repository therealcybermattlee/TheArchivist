"""Integration: the `archivist audit` command (006 US1).

Covers the report-only default, the --apply path, exit codes, and offline gap
detection against a seeded catalog.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import archivist.icloud as icloud
from archivist.cli import app
from archivist.icloud import Listing

from ._pullhelp import mock_enumerate, read_meta, seed_assets, write_config

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}
LIB = ["2026/09/IMG_1.HEIC", "2026/09/IMG_1.MOV", "2026/10/IMG_2.HEIC"]


def setup(cfg, tmp_path, **extra):
    return write_config(tmp_path, cfg, SOURCES, **extra)


def test_clean_source_reports_without_writing(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path)
    seed_assets(cfg, "demo", LIB)
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert "nothing missing" in res.output
    assert "dry-run" in res.output
    # Report-only: no state may move (Principle II).
    assert read_meta(cfg, "reconcile_state:demo") is None
    assert read_meta(cfg, "audit_state:demo") is None


def test_apply_reconciles_and_journals(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path)
    seed_assets(cfg, "demo", LIB)
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert "RECONCILED" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is not None
    assert read_meta(cfg, "audit_state:demo") is not None

    journals = list(cfg.logs_dir.glob("pull-*.jsonl"))
    assert journals, "an audit must leave a journal record"
    rec = json.loads(journals[0].read_text().splitlines()[0])
    assert rec["kind"] == "audit"
    assert rec["verdict"] == "reconciled"
    assert rec["missing"] == 0
    assert rec["reconcile_advanced_to"]


def test_gap_is_detected_and_reported(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path)
    seed_assets(cfg, "demo", LIB[:1])          # two of three never filed
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 1
    assert "2 missing (upper bound)" in res.output
    assert "2026-09" in res.output and "2026-10" in res.output
    # Looked, but not clean: audit_state moves, reconcile_state does not.
    assert read_meta(cfg, "audit_state:demo") is not None
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_incomplete_listing_is_unverified(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path)
    seed_assets(cfg, "demo", LIB)
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate(
        [], paths=[], complete=False, notes=("listing ended mid-line",)))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 1
    assert "could not verify" in res.output
    # Nothing is claimed on an unproven listing — not even "we looked".
    assert read_meta(cfg, "audit_state:demo") is None
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_interval_skips_a_recent_audit(cfg, tmp_path, monkeypatch):
    from ._pullhelp import fresh, seed_meta
    path = setup(cfg, tmp_path, audit_interval_days=7)
    seed_assets(cfg, "demo", LIB)
    seed_meta(cfg, {"audit_state:demo": fresh(2)})
    calls: list = []
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate(calls, paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--config", str(path)])
    assert res.exit_code == 0
    assert calls == [], "a source inside the interval must not be enumerated"


def test_force_overrides_the_interval(cfg, tmp_path, monkeypatch):
    from ._pullhelp import fresh, seed_meta
    path = setup(cfg, tmp_path, audit_interval_days=7)
    seed_assets(cfg, "demo", LIB)
    seed_meta(cfg, {"audit_state:demo": fresh(2)})
    calls: list = []
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate(calls, paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--force",
                              "--config", str(path)])
    assert res.exit_code == 0
    assert len(calls) == 1


def test_source_and_all_are_mutually_exclusive(cfg, tmp_path):
    path = setup(cfg, tmp_path)
    res = runner.invoke(app, ["audit", "--source", "demo", "--all",
                              "--config", str(path)])
    assert res.exit_code == 2


def test_unknown_source_exits_two(cfg, tmp_path):
    path = setup(cfg, tmp_path)
    res = runner.invoke(app, ["audit", "--source", "nope", "--config", str(path)])
    assert res.exit_code == 2


def test_the_full_missing_list_is_written_for_inspection(cfg, tmp_path, monkeypatch):
    """FR-004. A count says there is a problem; the list says whether it is real.

    The count is an upper bound, so the only way to tell a genuine gap from
    collision-suffix noise is to look at the names.
    """
    path = setup(cfg, tmp_path)
    seed_assets(cfg, "demo", LIB[:1])
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    written = list(cfg.logs_dir.glob("audit-*-demo-missing.txt"))
    assert written, res.output
    lines = written[0].read_text().strip().splitlines()
    assert sorted(lines) == sorted(LIB[1:])
