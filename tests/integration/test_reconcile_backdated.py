"""Integration: a sweep reaches media the routine window cannot (005 FR-017).

Items added to iCloud recently but CAPTURED long ago fall outside both the
recency bound and the date filter. Only an unbounded sweep sees them — which is
why a bounded routine scan may not ship without reconciliation behind it.
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


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run(conf, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args])


def test_a_due_sweep_drops_both_bounds(conf, cfg, monkeypatch):
    """FR-017: the sweep must be able to see items captured before the watermark.

    A date filter would exclude exactly those, making the sweep blind to the one
    class of media it exists to catch.
    """
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply")
    assert calls[0]["recent"] is None
    assert calls[0]["since"] is None
    assert calls[0]["until"] is None


def test_a_bootstrap_full_also_drops_the_date_filter(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply", "--full")
    assert calls[0]["since"] is None and calls[0]["recent"] is None


def test_a_bounded_run_keeps_the_recency_bound(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run(conf, "--apply")
    assert calls[0]["recent"] == 500


def test_explicit_since_reaches_behind_the_watermark(conf, cfg, monkeypatch):
    """FR-018: the documented path to re-cover a known gap.

    This is the shape of the 2026-09-26 repair: a back-dated pull that reaches
    behind the (wrongly advanced) watermark and may honestly advance it after.
    """
    seed_source(cfg, "acct-a", pull_state="2026-09-26T13:50:13",
                reconcile_state=fresh())
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls, proof=COVERED))
    result = run(conf, "--apply", "--since", "2026-08-19")
    assert calls[0]["since"] == "2026-08-19"
    assert calls[0]["recent"] is None            # unbounded: it must reach back
    assert result.exit_code == 0
    assert read_meta(cfg, "pull_state:acct-a") != "2026-09-26T13:50:13"
