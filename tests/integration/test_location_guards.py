"""Integration: guard rails for the location commands (US1 / baseline SC-007)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from archivist.catalog import Catalog
from archivist.cli import app

runner = CliRunner()


def test_scan_locations_refuses_without_archive_sentinel(cfg, config_file, fake_volumes):
    cat = Catalog(cfg.catalog_db)
    cat.init_db()
    with cat.connect() as conn:
        conn.execute("INSERT INTO assets(archive_path) VALUES('/nope/a.jpg')")
        conn.commit()

    sentinel = fake_volumes["archive"] / ".archivist-volume-id"
    sentinel.unlink()
    try:
        result = runner.invoke(app, ["scan-locations", "--config", str(config_file)])
        assert result.exit_code != 0
        out = result.output + str(result.exception or "")
        try:
            out += result.stderr  # click >= 8.2 captures stderr separately
        except (ValueError, AttributeError):
            pass
        assert "archive_root" in out and "guard" in out.lower()
        # Nothing examined: every row still NULL.
        with cat.connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE gps_status IS NOT NULL"
            ).fetchone()[0]
        assert n == 0
    finally:
        sentinel.write_text("test-volume\n", encoding="utf-8")


def test_export_map_refuses_without_archive_sentinel(cfg, config_file, fake_volumes):
    sentinel = fake_volumes["archive"] / ".archivist-volume-id"
    sentinel.unlink()
    try:
        result = runner.invoke(app, ["export-map", "--config", str(config_file)])
        assert result.exit_code != 0
        exports = fake_volumes["work"] / "TheArchivist" / "exports"
        assert not any(exports.iterdir())  # nothing written
    finally:
        sentinel.write_text("test-volume\n", encoding="utf-8")
