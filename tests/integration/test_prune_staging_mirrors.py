"""Integration: iCloud mirrors stay prunable, and pruning never breaks a pull.

005 FR-029. The mirror is transient pass-through storage (feature 004), which
is precisely why the routine pull may not rely on its contents — and why the
date filter stays alongside the count bound. Guards both halves.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import COVERED, fresh, mock_download, read_meta, seed_source, write_config

from archivist import icloud, staging
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def test_icloud_mirror_is_inside_the_prunable_roots(cfg):
    roots = staging.staging_roots(cfg)
    mirror = (cfg.icloud_dir / "acct-a")
    mirror.mkdir(parents=True, exist_ok=True)
    assert any(r == mirror or r in mirror.resolve().parents for r in roots)


def test_routine_pull_works_against_an_empty_mirror(conf, cfg, monkeypatch):
    """A pruned mirror must not be read as 'nothing has ever been downloaded'."""
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    result = runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                                 "--config", str(conf), "--apply"])
    assert result.exit_code == 0, result.output
    assert calls[0]["since"] == "2026-09-13"       # date filter still applied
    assert read_meta(cfg, "pull_state:acct-a") is not None


def test_empty_mirror_is_not_evidence_of_coverage(conf, cfg, monkeypatch):
    """An empty mirror plus an unconfirmed download must refuse, not advance."""
    from _pullhelp import UNCONFIRMED
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=UNCONFIRMED))
    runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                        "--config", str(conf), "--apply"])
    assert read_meta(cfg, "pull_state:acct-a") == "2026-09-20T08:00:00"
