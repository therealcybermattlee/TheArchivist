"""Integration: `pull all` — routine refresh across every iCloud source.

icloud.download is mocked (no network). What matters here is the fan-out
contract: only iCloud sources are touched, one source failing never stops or
corrupts the others, and per-source state stays independent.

Amended by feature 005: `download` now returns a CoverageProof rather than an
exit code, and the summary distinguishes a source that had nothing to do from
one that could not do its work.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, fresh, mock_download, read_meta,
                       seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()

STATE = "2026-07-31T12:00:00"
SOURCES = {
    "acct-a": {"type": "icloud", "device_folder": "A Cell", "username": "a@example.com"},
    "acct-b": {"type": "icloud", "device_folder": "B Cell", "username": "b@example.com"},
    "acct-c": {"type": "icloud", "device_folder": "C Cell", "username": "c@example.com"},
    "some-drop": {"type": "drop", "device_folder": "Drop Folder"},
}


@pytest.fixture
def multi_config(fake_volumes, cfg):
    """Three iCloud accounts + a drop source that must be left alone."""
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def seed_all(cfg, *sources, when=STATE):
    for s in sources:
        # Fresh reconcile state keeps these on the bounded path; reconciliation
        # has its own suite.
        seed_source(cfg, s, pull_state=when, reconcile_state=fresh())


def run_all(conf, *args):
    return runner.invoke(app, ["pull", "all", "--config", str(conf), *args])


def test_pulls_every_icloud_source_and_skips_non_icloud(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run_all(multi_config, "--apply")
    assert result.exit_code == 0, result.output
    assert [c["username"] for c in calls] == ["a@example.com", "b@example.com",
                                              "c@example.com"]
    # Every account used its own stored window; the drop source was never pulled.
    assert all(c["since"] == "2026-07-24" for c in calls)
    assert "some-drop" not in result.output


def test_one_failure_does_not_stop_or_corrupt_the_others(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(
        calls, proof=COVERED, proof_for={"b@example.com": UNCONFIRMED}))
    result = run_all(multi_config, "--apply")
    assert result.exit_code == 1, result.output          # surfaced, not swallowed
    assert len(calls) == 3                               # c still ran after b failed
    # Healthy sources advanced; the failed one kept its old window to retry.
    assert read_meta(cfg, "pull_state:acct-a") != STATE
    assert read_meta(cfg, "pull_state:acct-c") != STATE
    assert read_meta(cfg, "pull_state:acct-b") == STATE
    assert "FAILED" in result.output and "acct-b" in result.output


def test_never_bootstrapped_source_is_reported_not_guessed(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-c")                    # acct-b never pulled
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(calls))
    result = run_all(multi_config, "--apply")
    assert result.exit_code == 1
    # Refused BEFORE downloading anything for acct-b.
    assert [c["username"] for c in calls] == ["a@example.com", "c@example.com"]
    assert "--full --apply" in result.output             # actionable bootstrap hint


def test_stop_on_error_halts_the_run(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download", mock_download(
        calls, proof=COVERED, proof_for={"a@example.com": UNCONFIRMED}))
    result = run_all(multi_config, "--apply", "--stop-on-error")
    assert result.exit_code == 1
    assert len(calls) == 1                               # never reached b or c


def test_dry_run_advances_nothing(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    monkeypatch.setattr(icloud, "download", mock_download([]))
    result = run_all(multi_config)
    assert result.exit_code == 0, result.output
    assert all(read_meta(cfg, f"pull_state:{s}") == STATE
               for s in ("acct-a", "acct-b", "acct-c"))


def test_summary_distinguishes_idle_from_failed(multi_config, cfg, monkeypatch):
    """The distinction whose absence let the 2026-09-26 loss pass unnoticed.

    Before 005 both of these printed as `OK ... copied 0`.
    """
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    monkeypatch.setattr(icloud, "download", mock_download(
        [], proof=COVERED, proof_for={"b@example.com": UNCONFIRMED}))
    out = run_all(multi_config, "--apply").output
    idle_line = next(ln for ln in out.splitlines() if "acct-a" in ln and "IDLE" in ln)
    failed_line = next(ln for ln in out.splitlines() if "acct-b" in ln and "FAILED" in ln)
    assert "nothing new" in idle_line
    assert "could not be confirmed" in failed_line


def test_summary_reports_coverage_per_source(multi_config, cfg, monkeypatch):
    seed_all(cfg, "acct-a", "acct-b", "acct-c")
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    out = run_all(multi_config, "--apply").output
    assert out.count("covered through") == 3
