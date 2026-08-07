"""Integration: windowed pull state through the CLI (004 FR-015).

icloud.download is mocked (no network); the state machinery, refusal path,
and advancement rules are exercised end-to-end through the typer app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archivist import icloud
from archivist.catalog import Catalog
from archivist.cli import app

runner = CliRunner()


@pytest.fixture
def icloud_config(fake_volumes, cfg):
    import yaml
    path = fake_volumes["tmp"] / "config.yaml"
    path.write_text(yaml.safe_dump({
        "archive_root": str(cfg.archive_root),
        "work_root": str(cfg.work_root),
        "default_timezone": cfg.default_timezone,
        "sources": {
            "matt-personal": {"type": "icloud", "device_folder": "Matt Personal Cell",
                              "username": "test@example.com"},
        },
    }), encoding="utf-8")
    Catalog(cfg.catalog_db).init_db()
    return path


def _mock_download(calls):
    def fake(username, mirror, session_dir, recent=None, until_found=None,
             since=None, until=None, dry_run=False):
        calls.append({"since": since, "until": until, "recent": recent})
        Path(mirror).mkdir(parents=True, exist_ok=True)
        return 0
    return fake


def test_stateless_bare_pull_refuses(icloud_config, monkeypatch):
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--config", str(icloud_config)])
    assert result.exit_code == 2
    assert calls == []  # refused BEFORE any download
    out = result.output + getattr(result, "stderr", "")
    assert "--recent" in out and "--full" in out


def test_explicit_window_runs_and_advances_state_on_apply(icloud_config, cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--recent", "5", "--apply",
                                 "--config", str(icloud_config)])
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["recent"] == 5
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        assert cat.get_meta(conn, "pull_state:matt-personal") is not None


def test_dry_run_does_not_advance_state(icloud_config, cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--recent", "5", "--config", str(icloud_config)])
    assert result.exit_code == 0, result.output
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        assert cat.get_meta(conn, "pull_state:matt-personal") is None


def test_bare_pull_uses_stored_window(icloud_config, cfg, monkeypatch):
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        cat.set_meta(conn, "pull_state:matt-personal", "2026-07-31T12:00:00")
        conn.commit()
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--config", str(icloud_config)])
    assert result.exit_code == 0, result.output
    assert calls[0]["since"] == "2026-07-24"  # last_pull − 7-day overlap


def test_historical_range_slice_never_advances_state(icloud_config, cfg, monkeypatch):
    """A --since/--until slice is historical backfill — pull state must not move."""
    calls = []
    monkeypatch.setattr(icloud, "download", _mock_download(calls))
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--since", "2013-01-01", "--until", "2014-01-07",
                                 "--apply", "--config", str(icloud_config)])
    assert result.exit_code == 0, result.output
    assert calls[0]["since"] == "2013-01-01" and calls[0]["until"] == "2014-01-07"
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        assert cat.get_meta(conn, "pull_state:matt-personal") is None


def test_failed_download_does_not_advance_state(icloud_config, cfg, monkeypatch):
    cat = Catalog(cfg.catalog_db)
    with cat.connect() as conn:
        cat.set_meta(conn, "pull_state:matt-personal", "2026-07-31T12:00:00")
        conn.commit()
    monkeypatch.setattr(icloud, "download",
                        lambda *a, **kw: 1)  # icloudpd failure
    result = runner.invoke(app, ["pull", "icloud", "--source", "matt-personal",
                                 "--apply", "--config", str(icloud_config)])
    assert result.exit_code != 0
    with cat.connect() as conn:
        assert cat.get_meta(conn, "pull_state:matt-personal") == "2026-07-31T12:00:00"
