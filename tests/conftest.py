"""Shared test fixtures: fake sentinel volumes, config factory, GPS media.

Integration tests run against tmp-dir fake volumes carrying real
`.archivist-volume-id` sentinels — never against /Volumes/*.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from build_fixtures import build_all, tools_available  # noqa: E402

from archivist.config import Config, Source, load_config  # noqa: E402

requires_media_tools = pytest.mark.skipif(
    not tools_available(), reason="exiftool/ffmpeg not all on PATH"
)


@pytest.fixture
def fake_volumes(tmp_path: Path) -> dict[str, Path]:
    """Fake archive + work mounts with sentinel files and the work-dir layout."""
    archive = tmp_path / "archive"
    work = tmp_path / "work"
    for root in (archive, work):
        root.mkdir()
        (root / ".archivist-volume-id").write_text("test-volume\n", encoding="utf-8")
    for sub in ("staging", "drops", "logs", "catalog", "exports"):
        (work / "TheArchivist" / sub).mkdir(parents=True)
    return {"archive": archive, "work": work, "tmp": tmp_path}


@pytest.fixture
def cfg(fake_volumes: dict[str, Path]) -> Config:
    return Config(
        archive_root=fake_volumes["archive"],
        work_root=fake_volumes["work"],
        default_timezone="America/Detroit",
        sources={
            "peepaw-cell": Source(key="peepaw-cell", type="drop", device_folder="Peepaw Cell"),
        },
    )


@pytest.fixture
def config_file(fake_volumes: dict[str, Path], cfg: Config) -> Path:
    """A real config.yaml for CLI invocations, matching the `cfg` fixture."""
    path = fake_volumes["tmp"] / "config.yaml"
    path.write_text(yaml.safe_dump({
        "archive_root": str(cfg.archive_root),
        "work_root": str(cfg.work_root),
        "default_timezone": cfg.default_timezone,
        "sources": {
            "peepaw-cell": {"type": "drop", "device_folder": "Peepaw Cell"},
        },
    }), encoding="utf-8")
    assert load_config(path).archive_root == cfg.archive_root
    return path


@pytest.fixture(scope="session")
def gps_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """GPS fixture media, built once per session (skips if tools missing)."""
    if not tools_available():
        pytest.skip("exiftool/ffmpeg not all on PATH")
    return build_all(tmp_path_factory.mktemp("gps-media"))
