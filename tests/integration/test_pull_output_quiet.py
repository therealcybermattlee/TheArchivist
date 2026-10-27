"""Integration: default verbosity is legible (005 US4, FR-024, SC-008).

The run that motivated this feature emitted thousands of DEBUG skip lines per
source. The evidence is still captured — it is what proves a bounded scan
cleared its window — but the operator is shown a summary instead.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import COVERED, fresh, mock_download, seed_source, write_config

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}

NOISE = [f"2026-09-26 13:52:20 DEBUG    Skipping IMG_{n}.HEIC, as it was created "
         f"2025-01-12 14:06:52.743000-05:00, before 2026-09-19 00:00:00-04:00."
         for n in range(8000, 9000)]


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def noisy_download(verbose_seen):
    def fake(username, mirror, session_dir, verbose=False, on_line=None, **kw):
        verbose_seen.append(verbose)
        from pathlib import Path
        Path(mirror).mkdir(parents=True, exist_ok=True)
        if verbose:                       # only a verbose run echoes raw lines
            for line in NOISE:
                print(line)
        return COVERED
    return fake


def run(conf, *args):
    return runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                               "--config", str(conf), *args])


def test_default_run_shows_no_per_item_narration(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", noisy_download([]))
    out = run(conf, "--apply").output
    assert "as it was created" not in out
    assert "Skipping IMG_" not in out


def test_default_run_is_at_most_ten_lines_for_the_source(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", noisy_download([]))
    out = run(conf, "--apply").output
    body = [ln for ln in out.splitlines() if ln.strip()]
    assert len(body) <= 10, body


def test_the_summary_states_what_happened(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    monkeypatch.setattr(icloud, "download", mock_download([], proof=COVERED))
    out = run(conf, "--apply").output
    assert "routine: bounded scan (500)" in out      # path taken
    assert "examined 120" in out                     # counts
    assert "coverage advanced ->" in out             # outcome
