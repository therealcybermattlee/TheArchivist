"""Integration: unfiled mirror files block a clean verdict (006 FR-008).

This is the ONLY identified route to a false "reconciled". The listing omits
items the mirror already holds, so a file downloaded but not yet filed is
absent from the listing AND from the catalog. The difference reads empty while
the archive is genuinely missing it.

In normal operation the mirror is pruned and this guard never fires. It exists
because the one time it would matter, it would matter silently.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import archivist.icloud as icloud
from archivist.cli import app

from ._pullhelp import mock_enumerate, read_meta, seed_assets, write_config

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}
LIB = ["2026/09/IMG_1.HEIC", "2026/10/IMG_2.HEIC"]


def test_unfiled_mirror_file_prevents_reconciliation(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB)

    # A third item sits in the mirror, downloaded but never filed. The listing
    # does not mention it (it is already local) and the catalog does not know
    # it, so a naive diff is empty.
    mirror = cfg.icloud_dir / "demo" / "2026" / "11"
    mirror.mkdir(parents=True)
    (mirror / "IMG_3.HEIC").write_bytes(b"not yet filed")

    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])

    assert res.exit_code == 1
    assert "not yet filed" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_a_fully_filed_mirror_does_not_block(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB)
    for rel in LIB:
        p = cfg.icloud_dir / "demo" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"filed")

    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 0, res.output
    assert read_meta(cfg, "reconcile_state:demo") is not None


def test_dotfiles_in_the_mirror_are_not_unfiled_media(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    seed_assets(cfg, "demo", LIB)
    d = cfg.icloud_dir / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".DS_Store").write_bytes(b"noise")

    monkeypatch.setattr(icloud, "enumerate_library",
                        mock_enumerate([], paths=LIB))
    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 0, res.output
