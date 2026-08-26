"""Integration: `pull all` — routine refresh across every iCloud source.

icloud.download is mocked (no network). What matters here is the fan-out
contract: only iCloud sources are touched, one source failing never stops
or corrupts the others, and per-source pull state stays independent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archivist import icloud
from archivist.catalog import Catalog
from archivist.cli import app

runner = CliRunner()

STATE = "2026-07-31T12:00:00"


@pytest.fixture
def multi_config(fake_volumes, cfg):
    """Three iCloud accounts + a drop source that must be left alone."""
    import yaml
    path = fake_volumes["tmp"] / "config.yaml"
    path.write_text(yaml.safe_dump({
        "archive_root": str(cfg.archive_root),
        "work_root": str(cfg.work_root),
        "default_timezone": cfg.default_timezone,
        "sources": {
            "acct-a": {"type": "icloud", "device_folder": "A Cell",
                       "username": "a@example.com"},
            "acct-b": {"type": "icloud", "device_folder": "B Cell",
                       "username": "b@example.com"},
            "acct-c": {"type": "icloud", "device_folder": "C Cell",
                       "username": "c@example.com"},
            "some-drop": {"type": "drop", "device_folder": "Drop Folder"},
        },
    }), encoding="utf-8")
    Catalog(cfg.catalog_db).init_db()
    return path


def _seed_state(cfg, *sources, when=STATE):
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        for s in sources:
            cat.set_meta(conn, f"pull_state:{s}", when)
        conn.commit()


def _mock_download(calls, fail_for=()):
    def fake(username, mirror, session_dir, recent=None, until_found=None,
             since=None, until=None, dry_run=False):
        calls.append({"username": username, "since": since})
        if username in fail_for:
            return 1
        Path(mirror).mkdir(parents=True, exist_ok=True)
        return 0
    return fake


def test_pulls_every_icloud_source_and_skips_non_icloud(multi_config, cfg, monkeypatch):
    _seed_state(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "all", "--apply",
                                 "--config", str(multi_config)])
    assert result.exit_code == 0, result.output
    assert [c["username"] for c in calls] == ["a@example.com", "b@example.com",
                                              "c@example.com"]
    # Every account used its own stored window; the drop source was never pulled.
    assert all(c["since"] == "2026-07-24" for c in calls)
    assert "some-drop" not in result.output


def test_one_failure_does_not_stop_or_corrupt_the_others(multi_config, cfg, monkeypatch):
    _seed_state(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download",
                        _mock_download(calls, fail_for=("b@example.com",)))
    result = runner.invoke(app, ["pull", "all", "--apply",
                                 "--config", str(multi_config)])
    assert result.exit_code == 1, result.output          # surfaced, not swallowed
    assert len(calls) == 3                               # c still ran after b failed
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        # Healthy sources advanced; the failed one kept its old window to retry.
        assert cat.get_meta(conn, "pull_state:acct-a") != STATE
        assert cat.get_meta(conn, "pull_state:acct-c") != STATE
        assert cat.get_meta(conn, "pull_state:acct-b") == STATE
    assert "FAIL" in result.output and "acct-b" in result.output


def test_never_bootstrapped_source_is_reported_not_guessed(multi_config, cfg, monkeypatch):
    _seed_state(cfg, "acct-a", "acct-c")                 # acct-b never pulled
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "all", "--apply",
                                 "--config", str(multi_config)])
    assert result.exit_code == 1
    # Refused BEFORE downloading anything for acct-b.
    assert [c["username"] for c in calls] == ["a@example.com", "c@example.com"]
    assert "--full --apply" in result.output             # actionable bootstrap hint


def test_stop_on_error_halts_the_run(multi_config, cfg, monkeypatch):
    _seed_state(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download",
                        _mock_download(calls, fail_for=("a@example.com",)))
    result = runner.invoke(app, ["pull", "all", "--apply", "--stop-on-error",
                                 "--config", str(multi_config)])
    assert result.exit_code == 1
    assert len(calls) == 1                               # never reached b or c


def test_dry_run_advances_nothing(multi_config, cfg, monkeypatch):
    _seed_state(cfg, "acct-a", "acct-b", "acct-c")
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "all", "--config", str(multi_config)])
    assert result.exit_code == 0, result.output
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        assert all(cat.get_meta(conn, f"pull_state:{s}") == STATE
                   for s in ("acct-a", "acct-b", "acct-c"))
