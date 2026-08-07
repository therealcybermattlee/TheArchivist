"""Unit tests: doctor checks with mocked probes (004 FR-007/FR-010)."""

from __future__ import annotations

from pathlib import Path

import pytest

from archivist import doctor as doc
from archivist.config import Config, Source


def _cfg(tmp_path: Path, with_icloud: bool) -> Config:
    a, w = tmp_path / "a", tmp_path / "w"
    a.mkdir(exist_ok=True); w.mkdir(exist_ok=True)
    sources = {}
    if with_icloud:
        sources["m"] = Source(key="m", type="icloud", device_folder="M", username="x@y.z")
    return Config(archive_root=a, work_root=w,
                  default_timezone="America/Detroit", sources=sources)


def _by_name(checks):
    return {c.name: c for c in checks}


def test_keyring_required_only_with_icloud_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "probe_keyring", lambda: (False, "no backend"))
    without = _by_name(doc.run_checks(_cfg(tmp_path, with_icloud=False)))
    assert without["keyring"].required is False
    with_ic = _by_name(doc.run_checks(_cfg(tmp_path, with_icloud=True)))
    assert with_ic["keyring"].required is True and with_ic["keyring"].ok is False


def test_icloudpd_required_only_with_icloud_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_version_of", lambda exe, args: None)
    checks = _by_name(doc.run_checks(_cfg(tmp_path, with_icloud=False)))
    assert checks["icloudpd"].required is False
    assert checks["exiftool"].required is True and checks["exiftool"].ok is False


def test_bad_timezone_fails_required(tmp_path):
    cfg = Config(archive_root=tmp_path, work_root=tmp_path,
                 default_timezone="Not/AZone")
    checks = _by_name(doc.run_checks(cfg))
    assert checks["timezone"].ok is False and checks["timezone"].required is True


def test_missing_roots_fail_config_check(tmp_path):
    cfg = Config(archive_root=tmp_path / "missing", work_root=tmp_path,
                 default_timezone="America/Detroit")
    checks = _by_name(doc.run_checks(cfg))
    assert checks["config-roots"].ok is False
    assert "missing" in checks["config-roots"].detail


def test_work_storage_budget_informational(tmp_path, monkeypatch):
    checks = _by_name(doc.run_checks(_cfg(tmp_path, with_icloud=False)))
    assert checks["work-storage"].required is False and checks["work-storage"].ok
    monkeypatch.setattr(doc, "_dir_usage", lambda p: doc.WORK_BUDGET_BYTES + 1)
    checks = _by_name(doc.run_checks(_cfg(tmp_path, with_icloud=False)))
    assert checks["work-storage"].ok is False
    assert "prune-staging" in checks["work-storage"].remedy


def test_probe_keyring_real_backend_roundtrip():
    # On a developer Mac this exercises the real Keychain; elsewhere it may
    # legitimately fail — we only assert the contract shape.
    ok, detail = doc.probe_keyring()
    assert isinstance(ok, bool) and isinstance(detail, str) and detail
