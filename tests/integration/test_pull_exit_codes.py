"""Integration: exit codes (005, contracts/cli-pull.md §4).

PARTIAL exits 0 deliberately: the run did real work and declined to over-claim.
Making that non-zero would train the operator to ignore a non-zero exit, which
is exactly how a real failure gets missed.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, WINDOW_NOT_CLEARED, fresh,
                       mock_download, seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run(conf, cfg, proof, *args):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00", reconcile_state=fresh())
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args]), proof


def test_covered_run_exits_zero(conf, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    result, _ = run(conf, cfg, COVERED, "--apply")
    assert result.exit_code == 0, result.output


def test_partial_run_exits_zero(conf, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([], proof=WINDOW_NOT_CLEARED))
    result, _ = run(conf, cfg, WINDOW_NOT_CLEARED, "--apply")
    assert result.exit_code == 0, result.output
    assert "coverage NOT advanced" in result.output


def test_failed_run_exits_one(conf, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([], proof=UNCONFIRMED))
    result, _ = run(conf, cfg, UNCONFIRMED, "--apply")
    assert result.exit_code == 1


def test_unknown_source_exits_two(conf, cfg):
    result = runner.invoke(app, ["pull", "icloud", "--source", "nope",
                                 "--config", str(conf)])
    assert result.exit_code == 2


def test_wrong_source_type_exits_two(fake_volumes, cfg):
    conf = write_config(fake_volumes["tmp"], cfg,
                        {"d": {"type": "drop", "device_folder": "Drop"}})
    result = runner.invoke(app, ["pull", "icloud", "--source", "d",
                                 "--config", str(conf)])
    assert result.exit_code == 2


def test_bootstrap_needed_exits_one(conf, cfg, monkeypatch):
    monkeypatch.setattr(icloud, "download", mock_download([]))
    result = runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                                 "--config", str(conf), "--apply"])
    assert result.exit_code == 1
