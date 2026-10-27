"""Integration: budgeted repair of a detected gap (006 US3).

The gap is fetched by date range, never by sweeping the library. The
reconciliation claim comes from the RE-AUDIT afterwards, not from the fetch
having run — a repair that leaves items missing must not be able to call the
source reconciled.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import archivist.cli as cli
import archivist.icloud as icloud
from archivist.cli import app
from archivist.icloud import Listing

from ._pullhelp import mock_enumerate, read_meta, seed_assets, write_config

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}
LIB = [f"2026/09/IMG_{i}.HEIC" for i in range(4)] + \
      [f"2026/10/IMG_{i}.HEIC" for i in range(4)]


def listing_of(paths, complete=True):
    return Listing(paths=frozenset(paths), listed_lines=len(paths),
                   complete=complete)


def test_repair_fetches_only_the_affected_range(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB[:4])            # all of 2026-10 missing

    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    pulls: list = []

    def fake_pull(cfg_, source, **kw):
        pulls.append((kw.get("since"), kw.get("until")))
        # Simulate the fetch filing the rest.
        seed_assets(cfg_, "demo", LIB[4:])
        return cli.PullOutcome(source, "ok")

    monkeypatch.setattr(cli, "_pull_one", fake_pull)

    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--repair", "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert pulls == [("2026-10-01", "2026-10-31")], pulls
    assert "within budget" in res.output
    assert "after repair: 0 still missing" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is not None


def test_a_repair_that_leaves_items_missing_withholds_the_watermark(
        cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB[:4])
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    # The fetch runs but files nothing.
    monkeypatch.setattr(cli, "_pull_one",
                        lambda cfg_, source, **kw: cli.PullOutcome(source, "ok"))

    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--repair", "--config", str(path)])
    assert res.exit_code == 1
    assert "after repair: 4 still missing" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_over_budget_reports_without_fetching(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES, repair_budget_gb=0.000001)
    seed_assets(cfg, "demo", LIB[:4])
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    monkeypatch.setattr(cli, "_pull_one",
                        lambda *a, **k: pytest.fail("must not fetch over budget"))

    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--repair", "--config", str(path)])
    assert res.exit_code == 1
    assert "not repairing" in res.output and "exceeds" in res.output


def test_auto_repair_disabled_never_fetches(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES, auto_repair=False)
    seed_assets(cfg, "demo", LIB[:4])
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    monkeypatch.setattr(cli, "_pull_one",
                        lambda *a, **k: pytest.fail("auto_repair is off"))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--repair", "--config", str(path)])
    assert res.exit_code == 1
    assert "disabled" in res.output


def test_scattered_gap_is_never_swept(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    scattered = [f"2026/{m:02d}/IMG.HEIC" for m in range(1, 13)]
    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=scattered))
    monkeypatch.setattr(cli, "_pull_one",
                        lambda *a, **k: pytest.fail("must not sweep"))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--repair", "--config", str(path)])
    assert res.exit_code == 1
    assert "full sweep" in res.output


def test_repair_requires_apply(cfg, tmp_path):
    path = write_config(tmp_path, cfg, SOURCES)
    res = runner.invoke(app, ["audit", "--source", "demo", "--repair",
                              "--config", str(path)])
    assert res.exit_code == 2
    assert "requires --apply" in res.output


def test_repair_journals_its_decision(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB[:4])
    monkeypatch.setattr(icloud, "enumerate_library", mock_enumerate([], paths=LIB))
    monkeypatch.setattr(cli, "_pull_one",
                        lambda cfg_, source, **kw: cli.PullOutcome(source, "ok"))
    runner.invoke(app, ["audit", "--source", "demo", "--apply", "--repair",
                        "--config", str(path)])
    rec = json.loads(
        list(cfg.logs_dir.glob("pull-*.jsonl"))[0].read_text().splitlines()[-1])
    assert rec["kind"] == "audit_repair"
    assert rec["decision"] == "repair"
    assert rec["ranges"] == ["2026-10-01..2026-10-31"]
    assert rec["missing_after"] == 4
