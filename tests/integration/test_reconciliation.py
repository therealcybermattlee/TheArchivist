"""Integration: auto-escalating reconciliation (005 US2, FR-011..FR-017).

A bounded routine scan cannot see media added recently but captured long ago,
so it must be paired with a periodic unbounded sweep. That sweep is also what
repairs coverage after the fact — including holes an earlier premature
watermark left behind.
"""

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
}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def run_all(conf, *args):
    return runner.invoke(app, ["pull", "all", "--config", str(conf), *args])


def test_stale_source_escalates_to_an_unbounded_sweep(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run_all(conf, "--apply")
    by_user = {c["username"]: c for c in calls}
    # A sweep drops BOTH bounds. Asserting only `recent` here is what let a
    # date-filtered "sweep" — unable to see anything older than the watermark —
    # ship green.
    assert by_user["a@example.com"]["recent"] is None
    assert by_user["a@example.com"]["since"] is None
    assert by_user["b@example.com"]["recent"] == 500      # bounded routine
    assert by_user["b@example.com"]["since"] is not None  # and still date-filtered
    assert "reconciliation due" in result.output


def test_sweep_announces_itself_before_scanning(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    monkeypatch.setattr(icloud, "download", mock_download([]))
    out = run_all(conf, "--apply").output
    assert "this will take longer" in out
    assert "40d ago" in out


def test_never_reconciled_source_is_due(conf, cfg, monkeypatch):
    """No reconcile watermark => due. This is what repairs pre-existing holes."""
    seed_source(cfg, "acct-a", pull_state=fresh(1))       # no reconcile_state
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run_all(conf, "--apply")
    assert {c["username"]: c["recent"] for c in calls}["a@example.com"] is None


def test_clean_sweep_advances_both_watermarks(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run_all(conf, "--apply")
    assert read_meta(cfg, "reconcile_state:acct-a") == read_meta(cfg, "pull_state:acct-a")


def test_bounded_run_never_advances_the_reconcile_watermark(conf, cfg, monkeypatch):
    before = fresh(2)
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=before)
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=before)
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    run_all(conf, "--apply")
    assert read_meta(cfg, "reconcile_state:acct-a") == before
    assert read_meta(cfg, "pull_state:acct-a") != before      # coverage did move


def test_failed_sweep_advances_neither(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-01-01T00:00:00",
                reconcile_state="2026-01-01T00:00:00")
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    monkeypatch.setattr(icloud, "download", mock_download(
        [], proof_for={"a@example.com": UNCONFIRMED}, proof=COVERED))
    run_all(conf, "--apply")
    assert read_meta(cfg, "pull_state:acct-a") == "2026-01-01T00:00:00"
    assert read_meta(cfg, "reconcile_state:acct-a") == "2026-01-01T00:00:00"


def test_no_reconcile_flag_suppresses_escalation_but_still_reports(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run_all(conf, "--apply", "--no-reconcile")
    assert {c["username"]: c["recent"] for c in calls}["a@example.com"] == 500
    assert "reconciliation due" in result.output       # overdue is still surfaced


def test_one_sweeping_source_does_not_stop_the_others(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(
        calls, proof_for={"a@example.com": UNCONFIRMED}, proof=COVERED))
    result = run_all(conf, "--apply")
    assert len(calls) == 2                             # b ran after a failed
    assert read_meta(cfg, "pull_state:acct-b") is not None
    assert result.exit_code == 1                       # surfaced, not swallowed


def test_interval_is_configurable_per_source(fake_volumes, cfg, monkeypatch):
    sources = dict(SOURCES)
    sources["acct-a"] = {**sources["acct-a"], "reconcile_interval_days": 5}
    conf = write_config(fake_volumes["tmp"], cfg, sources)
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(10))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(10))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run_all(conf, "--apply")
    modes = {c["username"]: c["recent"] for c in calls}
    assert modes["a@example.com"] is None    # 10d > 5d interval -> sweep
    assert modes["b@example.com"] == 500     # 10d < 30d default -> bounded


def test_single_source_pull_can_also_suppress_escalation(fake_volumes, cfg, monkeypatch):
    """`--no-reconcile` has parity on `pull icloud`.

    Without it, any routine single-source pull on a due source becomes a full
    sweep, which makes incremental testing on a real library impractical.
    """
    conf = write_config(fake_volumes["tmp"], cfg, SOURCES)
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                        "--config", str(conf), "--apply", "--no-reconcile"])
    assert calls[0]["recent"] == 500      # bounded, not swept
    assert calls[0]["since"] is not None


def test_auto_reconcile_false_suppresses_sweeps_but_never_the_warning(
        fake_volumes, cfg, monkeypatch):
    """The operator-scheduled mode chosen 2026-09-28.

    Switching escalation off must not switch off the reporting — otherwise a
    growing gap becomes invisible, which is the failure this feature exists to
    prevent, reintroduced by a config flag.
    """
    conf = write_config(fake_volumes["tmp"], cfg, SOURCES, auto_reconcile=False)
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run_all(conf, "--apply")
    assert {c["username"]: c["recent"] for c in calls}["a@example.com"] == 500
    assert "reconciliation due" in result.output
    assert "acct-a (40d)" in result.output
    assert "--full --apply" in result.output          # and what to run


def test_never_reconciled_source_is_reported_as_overdue(fake_volumes, cfg, monkeypatch):
    """Regression: the old filter keyed on an age that is None when a source has
    never been swept, so the MOST overdue sources were the ones it hid."""
    conf = write_config(fake_volumes["tmp"], cfg, SOURCES, auto_reconcile=False)
    for s in ("acct-a", "acct-b"):
        seed_source(cfg, s, pull_state=fresh(1))      # no reconcile_state at all
    monkeypatch.setattr(icloud, "download", mock_download([]))
    out = run_all(conf, "--apply").output
    assert "acct-a (never)" in out and "acct-b (never)" in out


def test_auto_reconcile_true_still_escalates(fake_volumes, cfg, monkeypatch):
    conf = write_config(fake_volumes["tmp"], cfg, SOURCES, auto_reconcile=True)
    seed_source(cfg, "acct-a", pull_state=fresh(1), reconcile_state=fresh(40))
    seed_source(cfg, "acct-b", pull_state=fresh(1), reconcile_state=fresh(2))
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    run_all(conf, "--apply")
    assert {c["username"]: c["recent"] for c in calls}["a@example.com"] is None
