"""Integration: --verbose restores the raw stream (005 FR-025)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import COVERED, fresh, seed_source, write_config

from archivist import icloud
from archivist.cli import app

runner = CliRunner()
SOURCES = {"acct-a": {"type": "icloud", "device_folder": "A Cell",
                      "username": "a@example.com"}}
SAMPLE = ("2026-09-26 13:52:20 DEBUG    Skipping IMG_8042.HEIC, as it was created "
          "2025-01-12 14:06:52.743000-05:00, before 2026-09-19 00:00:00-04:00.")


@pytest.fixture
def conf(fake_volumes, cfg):
    return write_config(fake_volumes["tmp"], cfg, SOURCES)


def echoing_download(seen):
    def fake(username, mirror, session_dir, verbose=False, on_line=None, **kw):
        seen.append(verbose)
        from pathlib import Path
        Path(mirror).mkdir(parents=True, exist_ok=True)
        if verbose:
            print(SAMPLE)
        return COVERED
    return fake


def test_verbose_flag_reaches_the_downloader(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    seen = []
    monkeypatch.setattr(icloud, "download", echoing_download(seen))
    out = runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                              "--config", str(conf), "--apply", "--verbose"]).output
    assert seen == [True]
    assert "as it was created" in out


def test_default_does_not_request_verbosity(conf, cfg, monkeypatch):
    seed_source(cfg, "acct-a", pull_state="2026-09-20T08:00:00",
                reconcile_state=fresh())
    seen = []
    monkeypatch.setattr(icloud, "download", echoing_download(seen))
    runner.invoke(app, ["pull", "icloud", "--source", "acct-a",
                        "--config", str(conf), "--apply"])
    assert seen == [False]


def test_pull_all_passes_verbose_to_every_source(fake_volumes, cfg, monkeypatch):
    sources = {**SOURCES, "acct-b": {"type": "icloud", "device_folder": "B Cell",
                                     "username": "b@example.com"}}
    conf = write_config(fake_volumes["tmp"], cfg, sources)
    for s in ("acct-a", "acct-b"):
        seed_source(cfg, s, pull_state="2026-09-20T08:00:00", reconcile_state=fresh())
    seen = []
    monkeypatch.setattr(icloud, "download", echoing_download(seen))
    runner.invoke(app, ["pull", "all", "--config", str(conf), "--apply", "--verbose"])
    assert seen == [True, True]
