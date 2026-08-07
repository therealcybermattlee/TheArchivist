"""Unit tests: host-aware config root validation (004 FR-007)."""

from pathlib import Path

from archivist.config import Config, validate_roots


def _cfg(archive: Path, work: Path) -> Config:
    return Config(archive_root=archive, work_root=work,
                  default_timezone="America/Detroit")


def test_valid_roots_pass(tmp_path: Path):
    a, w = tmp_path / "a", tmp_path / "w"
    a.mkdir(); w.mkdir()
    assert validate_roots(_cfg(a, w)) == []


def test_missing_root_reported_with_label(tmp_path: Path):
    a = tmp_path / "a"
    a.mkdir()
    errors = validate_roots(_cfg(a, tmp_path / "nope"))
    assert len(errors) == 1
    assert "work_root" in errors[0] and "nope" in errors[0]


def test_both_missing_reported(tmp_path: Path):
    errors = validate_roots(_cfg(tmp_path / "x", tmp_path / "y"))
    assert len(errors) == 2


def test_cross_host_path_hint(tmp_path: Path, monkeypatch):
    # Simulate a Linux host seeing a Mac-style path.
    import archivist.config as cfgmod
    monkeypatch.setattr("sys.platform", "linux")
    errors = validate_roots(_cfg(Path("/Volumes/DefinitelyNotMounted-xyz"), tmp_path))
    joined = " ".join(errors)
    assert "macOS-style" in joined and "config.yaml" in joined
