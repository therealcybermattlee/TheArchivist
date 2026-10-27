"""Integration: the routine refresh audits on an interval (006 US4).

The audit is cheap enough to run weekly, which is the whole point: the gap
that prompted this feature sat undetected for 61 days because the only thing
that would have found it cost 246 GB.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import archivist.cli as cli
import archivist.icloud as icloud
from archivist.cli import app

from ._pullhelp import (COVERED, fresh, mock_download, mock_enumerate,
                        read_meta, seed_assets, seed_meta, write_config)
from tests.unit.test_session_validity import COMPLETED, HANDSHAKE_ONLY, write_jar

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}
LIB = ["2026/09/IMG_1.HEIC", "2026/10/IMG_2.HEIC"]


def setup(cfg, tmp_path, monkeypatch, *, paths=LIB, archived=LIB, **extra):
    path = write_config(tmp_path, cfg, SOURCES, **extra)
    write_jar(cfg.icloud_session_dir, "demo@example.com", COMPLETED)
    seed_assets(cfg, "demo", archived)
    seed_meta(cfg, {"pull_state:demo": fresh(1)})
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    calls: list = []
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate(calls, paths=paths))
    return path, calls


def test_a_source_outside_the_interval_is_audited(cfg, tmp_path, monkeypatch):
    path, calls = setup(cfg, tmp_path, monkeypatch, audit_interval_days=7)
    seed_meta(cfg, {"audit_state:demo": fresh(30)})
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert len(calls) == 1
    assert "reconciled today" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is not None


def test_a_source_inside_the_interval_is_not_audited(cfg, tmp_path, monkeypatch):
    path, calls = setup(cfg, tmp_path, monkeypatch, audit_interval_days=7)
    seed_meta(cfg, {"audit_state:demo": fresh(2)})
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert calls == [], "listing is the expensive part; the interval exists to skip it"


def test_no_audit_suppresses_it(cfg, tmp_path, monkeypatch):
    path, calls = setup(cfg, tmp_path, monkeypatch)
    res = runner.invoke(app, ["pull", "all", "--apply", "--no-audit",
                              "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert calls == []


def test_audit_flag_forces_it_inside_the_interval(cfg, tmp_path, monkeypatch):
    path, calls = setup(cfg, tmp_path, monkeypatch, audit_interval_days=7)
    seed_meta(cfg, {"audit_state:demo": fresh(1)})
    res = runner.invoke(app, ["pull", "all", "--apply", "--audit",
                              "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert len(calls) == 1


def test_a_gap_is_surfaced_in_the_summary(cfg, tmp_path, monkeypatch):
    path, calls = setup(cfg, tmp_path, monkeypatch,
                        paths=LIB, archived=LIB[:1], auto_repair=False)
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 1
    assert "GAP" in res.output
    assert "missing 1 item(s)" in res.output or "missing 1" in res.output
    assert "repair the archive gap" in res.output


def test_a_dead_session_skips_the_audit_without_failing_the_pull(
        cfg, tmp_path, monkeypatch):
    """Enumerating a library we cannot reach wastes ten minutes to learn nothing."""
    path = write_config(tmp_path, cfg, SOURCES)
    write_jar(cfg.icloud_session_dir, "demo@example.com", HANDSHAKE_ONLY)
    seed_assets(cfg, "demo", LIB)
    seed_meta(cfg, {"pull_state:demo": fresh(1)})
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    monkeypatch.setattr(icloud, "enumerate_library",
                        lambda *a, **k: pytest.fail("must not enumerate"))
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 0, res.output


def test_a_failed_pull_is_not_audited(cfg, tmp_path, monkeypatch):
    from ._pullhelp import UNCONFIRMED
    path = write_config(tmp_path, cfg, SOURCES)
    write_jar(cfg.icloud_session_dir, "demo@example.com", COMPLETED)
    seed_meta(cfg, {"pull_state:demo": fresh(1)})
    monkeypatch.setattr(icloud, "download", mock_download([], proof=UNCONFIRMED))
    monkeypatch.setattr(icloud, "enumerate_library",
                        lambda *a, **k: pytest.fail("must not enumerate"))
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 1
