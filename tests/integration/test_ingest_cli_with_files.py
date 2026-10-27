"""Integration: the ingest CLI path with REAL files in the directory.

Every other pull/ingest test mocks the downloader and leaves the mirror empty,
so `_run_ingest` returned at the "no files" guard and the planning code below
it was never executed by any test. A `NameError` on the plan-progress line
therefore survived a 313-test suite and only surfaced by crashing a live
33,124-file sweep.

These tests exist to make that path reachable: a directory with actual files,
driven through the CLI exactly as an operator drives it.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from _pullhelp import write_config

from archivist import ingest as ing
from archivist.catalog import Catalog
from archivist.cli import app

runner = CliRunner()
SOURCES = {"drop-a": {"type": "drop", "device_folder": "A Cell"}}


@pytest.fixture
def staged(fake_volumes, cfg, monkeypatch):
    """A drop directory holding several real files."""
    monkeypatch.setattr(ing, "extract_batch", lambda paths: {})
    conf = write_config(fake_volumes["tmp"], cfg, SOURCES)
    Catalog(cfg.catalog_db).init_db()
    d = cfg.drops_dir / "drop-a"
    d.mkdir(parents=True, exist_ok=True)
    for n in range(12):
        (d / f"IMG_{n:04d}.JPG").write_bytes(f"photo {n} ".encode() * 300)
    return {"conf": conf, "dir": d, "cfg": cfg}


def invoke(staged, *args):
    r = runner.invoke(app, ["ingest", str(staged["dir"]), "--source", "drop-a",
                            "--config", str(staged["conf"]), *args])
    if r.exception and not isinstance(r.exception, SystemExit):
        raise r.exception          # never let a NameError hide as an exit code
    return r


def test_dry_run_plans_real_files_without_writing(staged):
    r = invoke(staged)
    assert r.exit_code == 0, r.output
    assert "to copy: 12" in r.output
    assert not any(staged["cfg"].archive_root.rglob("IMG_*.JPG"))


def test_apply_copies_and_verifies(staged):
    r = invoke(staged, "--apply")
    assert r.exit_code == 0, r.output
    assert "copied 12" in r.output
    filed = sorted(p.name for p in staged["cfg"].archive_root.rglob("IMG_*.JPG"))
    assert len(filed) == 12


def test_second_run_skips_everything_as_duplicate(staged):
    invoke(staged, "--apply")
    r = invoke(staged, "--apply")
    assert "already-archived (skip): 12" in r.output
    assert "copied 0" in r.output


def test_verify_archive_reaches_the_planner_with_real_files(staged):
    invoke(staged, "--apply")
    r = invoke(staged, "--verify-archive")
    assert r.exit_code == 0, r.output
    assert "--verify-archive" in r.output
    assert "already-archived (skip): 12" in r.output


def test_plan_progress_line_is_emitted(staged, monkeypatch):
    """The line that crashed the live sweep. Forced to fire by dropping the
    5-second throttle to zero."""
    import archivist.cli as cli_mod
    real = cli_mod.time.monotonic
    monkeypatch.setattr(cli_mod.time, "monotonic",
                        lambda _c=[0]: (_c.__setitem__(0, _c[0] + 100), _c[0])[1])
    r = invoke(staged)
    assert r.exit_code == 0, r.output
    assert "planning" in (r.output + str(r.stderr or ""))
    monkeypatch.setattr(cli_mod.time, "monotonic", real)
