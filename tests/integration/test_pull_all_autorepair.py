"""Integration: budgeted self-repair inside the routine refresh (006 US4).

The operator chose this over report-only on 2026-10-27: it realizes the saved
bandwidth while keeping every branch of `pull all` bounded. The bound is the
point — the previous automatic branch could start a 246 GB sweep against a
~50 GB working volume.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import archivist.cli as cli
import archivist.icloud as icloud
from archivist.cli import app

from ._pullhelp import (COVERED, fresh, mock_download, mock_enumerate,
                        read_meta, seed_assets, seed_meta, write_config)
from tests.unit.test_session_validity import COMPLETED, write_jar

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}
LIB = [f"2026/10/IMG_{i}.HEIC" for i in range(4)]


def setup(cfg, tmp_path, monkeypatch, *, archived, **extra):
    path = write_config(tmp_path, cfg, SOURCES, **extra)
    write_jar(cfg.icloud_session_dir, "demo@example.com", COMPLETED)
    if archived:
        seed_assets(cfg, "demo", archived)
    seed_meta(cfg, {"pull_state:demo": fresh(1)})
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    return path


def test_within_budget_repairs_automatically(cfg, tmp_path, monkeypatch):
    # One item already filed, so the source has a median size to estimate from.
    # With none, FR-030 correctly refuses: no basis for an estimate must read
    # as "too large", never as "free".
    path = setup(cfg, tmp_path, monkeypatch, archived=LIB[:1])
    repairs: list = []
    real_pull = cli._pull_one

    def fake_pull(cfg_, source, **kw):
        if kw.get("since"):                      # the repair fetch
            repairs.append((kw["since"], kw["until"]))
            seed_assets(cfg_, "demo", LIB)
            return cli.PullOutcome(source, "ok")
        return real_pull(cfg_, source, **kw)

    monkeypatch.setattr(cli, "_pull_one", fake_pull)
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert repairs == [("2026-10-01", "2026-10-31")], res.output
    assert "after repair: 0 still missing" in res.output
    assert "within budget" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is not None
    assert res.exit_code == 0, res.output


def test_over_budget_reports_instead_of_fetching(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path, monkeypatch, archived=LIB[:1],
                 repair_budget_gb=0.000001)
    real_pull = cli._pull_one

    def fake_pull(cfg_, source, **kw):
        if kw.get("since"):
            pytest.fail("must not fetch over budget")
        return real_pull(cfg_, source, **kw)

    monkeypatch.setattr(cli, "_pull_one", fake_pull)
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 1
    assert "not repairing" in res.output
    assert "GAP" in res.output


def test_auto_repair_disabled_reduces_to_report_only(cfg, tmp_path, monkeypatch):
    path = setup(cfg, tmp_path, monkeypatch, archived=LIB[:1],
                 auto_repair=False)
    real_pull = cli._pull_one

    def fake_pull(cfg_, source, **kw):
        if kw.get("since"):
            pytest.fail("auto_repair is off")
        return real_pull(cfg_, source, **kw)

    monkeypatch.setattr(cli, "_pull_one", fake_pull)
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert res.exit_code == 1
    assert "disabled" in res.output


def test_a_dry_run_never_repairs(cfg, tmp_path, monkeypatch):
    """Principle II: approval is given per invocation, and none was given here."""
    path = setup(cfg, tmp_path, monkeypatch, archived=LIB[:1])
    real_pull = cli._pull_one

    def fake_pull(cfg_, source, **kw):
        if kw.get("since"):
            pytest.fail("a dry run must not fetch a repair")
        return real_pull(cfg_, source, **kw)

    monkeypatch.setattr(cli, "_pull_one", fake_pull)
    res = runner.invoke(app, ["pull", "all", "--config", str(path)])
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_no_median_size_means_no_automatic_repair(cfg, tmp_path, monkeypatch):
    """FR-030, found by writing this suite wrong the first time.

    A source that has never filed anything offers no basis for a size
    estimate. That must read as "too large to do unattended", not as "free".
    """
    path = setup(cfg, tmp_path, monkeypatch, archived=[])
    real_pull = cli._pull_one

    def fake_pull(cfg_, source, **kw):
        if kw.get("since"):
            pytest.fail("an unestimatable repair must not run automatically")
        return real_pull(cfg_, source, **kw)

    monkeypatch.setattr(cli, "_pull_one", fake_pull)
    res = runner.invoke(app, ["pull", "all", "--apply", "--config", str(path)])
    assert "could not be estimated" in res.output
    assert res.exit_code == 1
