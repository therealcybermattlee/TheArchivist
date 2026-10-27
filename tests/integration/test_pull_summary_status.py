"""Integration: the status vocabulary (005 FR-010/FR-027, contracts §3.2).

IDLE vs FAILED is the line that matters. On 2026-09-26 four sources printed as
`OK ... copied 0` while two of them had done nothing at all.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import (COVERED, UNCONFIRMED, WINDOW_NOT_CLEARED, fresh,
                       mock_download, seed_source, write_config)

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {
    "quiet": {"type": "icloud", "device_folder": "Q Cell", "username": "q@example.com"},
    "broken": {"type": "icloud", "device_folder": "B Cell", "username": "b@example.com"},
    "busy": {"type": "icloud", "device_folder": "Y Cell", "username": "y@example.com"},
    "virgin": {"type": "icloud", "device_folder": "V Cell", "username": "v@example.com"},
}


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


@pytest.fixture
def summary(conf, cfg, monkeypatch):
    for s in ("quiet", "broken", "busy"):        # "virgin" is never bootstrapped
        seed_source(cfg, s, pull_state="2026-09-20T08:00:00", reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED, proof_for={
        "b@example.com": UNCONFIRMED,
        "y@example.com": WINDOW_NOT_CLEARED,
    }))
    return runner.invoke(app, ["pull", "all", "--config", str(conf), "--apply"])


STATUSES = ("OK", "IDLE", "PARTIAL", "FAILED", "BOOTSTRP", "CONFIG")


def line_for(output: str, source: str) -> str:
    """The source's line in the Refresh summary block, not any other mention."""
    tail = output.split("Refresh summary", 1)[1]
    return next(ln for ln in tail.splitlines()
                if source in ln and any(s in ln for s in STATUSES))


def test_quiet_source_is_idle_not_ok(summary):
    assert "IDLE" in line_for(summary.output, "quiet")


def test_broken_source_is_failed(summary):
    assert "FAILED" in line_for(summary.output, "broken")


def test_idle_and_failed_are_visually_distinct(summary):
    assert line_for(summary.output, "quiet") != line_for(summary.output, "broken")


def test_busy_source_that_held_coverage_is_partial(summary):
    assert "PARTIAL" in line_for(summary.output, "busy")


def test_never_bootstrapped_source_is_flagged(summary):
    assert "BOOTSTRP" in line_for(summary.output, "virgin")


def test_partial_explains_itself_in_the_summary(summary):
    assert "scan_bound" in summary.output
