"""Integration: the coverage journal and its ordering (005 case 18, FR-007).

Constitution Principle IV: journal BEFORE the catalog. An interruption between
the two must leave a stale watermark, never a premature one — a stale watermark
re-covers ground, a premature one loses it.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, fresh, mock_download, read_meta,
                       seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def journals(cfg):
    return sorted(cfg.logs_dir.glob("pull-*.jsonl"))


def records(cfg):
    out = []
    for path in journals(cfg):
        out += [json.loads(line) for line in path.read_text().splitlines() if line]
    return out


def run(conf, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args])


def test_advance_is_journaled_with_what_it_claimed(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf, "--apply")
    (rec,) = records(cfg)
    assert rec["decision"] == "advance"
    assert rec["source"] == "acct-a"
    assert rec["window_since"] == "2026-09-13"     # watermark − 7-day overlap
    assert rec["claimed_through"] == rec["run_started"]
    assert rec["reason"] is None


def test_refusal_is_journaled_with_its_reason(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=UNCONFIRMED))
    run(conf, "--apply")
    (rec,) = records(cfg)
    assert rec["decision"] == "refuse"
    assert rec["claimed_through"] is None
    assert "could not be confirmed" in rec["reason"]
    # The incident's signature, now queryable rather than invisible.
    assert rec["downloaded"] == 0
    assert rec["enumeration_complete"] is False


def test_watermark_equals_run_start_not_run_finish(conf, cfg, monkeypatch):
    """Case 17. Items created DURING a long run must still be sought next time."""
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf, "--apply")
    (rec,) = records(cfg)
    assert rec["run_started"] <= rec["run_finished"]
    assert read_meta(cfg, "pull_state:acct-a") == rec["run_started"]
    assert read_meta(cfg, "pull_state:acct-a") != rec["run_finished"] or \
        rec["run_started"] == rec["run_finished"]


def test_journal_precedes_the_catalog_write(conf, cfg, monkeypatch):
    """Simulate a crash between the two writes: journal survives, watermark doesn't."""
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))

    import archivist.catalog as catalog_mod
    boom = RuntimeError("volume vanished mid-commit")

    def explode(self, conn, key, value):
        if key.startswith("pull_state:"):
            raise boom
    monkeypatch.setattr(catalog_mod.Catalog, "set_meta", explode)

    runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                        "--config", str(conf), "--apply"])
    # The journal recorded the intent...
    assert records(cfg) and records(cfg)[0]["decision"] == "advance"
    # ...but the watermark never moved. Stale, not premature.
    assert read_meta(cfg, "pull_state:acct-a") == "2026-09-20T08:00:00"


def test_dry_run_writes_no_journal(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf)
    assert journals(cfg) == []


def test_coverage_meta_mirrors_the_latest_record(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run(conf, "--apply")
    mirrored = json.loads(read_meta(cfg, "coverage:acct-a"))
    assert mirrored == records(cfg)[0]
