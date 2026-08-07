"""Unit tests: filing decisions are independent of the host timezone (SC-007).

The configured `default_timezone` governs every date decision; the host's
TZ environment must be irrelevant. We run resolution + target-dir math under
several TZ values and demand identical outputs.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from archivist.dates import resolve
from archivist.ingest import _target_dir

HOST_TZS = ["UTC", "America/Detroit", "Asia/Tokyo", "Pacific/Kiritimati"]

# A late-night Eastern video: 2024-06-16 03:59:58 UTC == 2024-06-15 23:59:58 EDT.
VIDEO_RAW = {"CreateDate": "2024:06:16 03:59:58"}
PHOTO_RAW = {"DateTimeOriginal": "2024:06:15 14:00:00"}


@pytest.fixture
def any_file(tmp_path: Path) -> Path:
    p = tmp_path / "IMG_0001.JPG"
    p.write_bytes(b"x")
    return p


def _with_tz(tz: str, fn):
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_photo_date_identical_across_host_tz(any_file: Path):
    results = {
        tz: _with_tz(tz, lambda: resolve(any_file, PHOTO_RAW, "America/Detroit",
                                         is_video=False).dt)
        for tz in HOST_TZS
    }
    assert len(set(results.values())) == 1
    assert next(iter(results.values())).date().isoformat() == "2024-06-15"


def test_video_utc_normalization_identical_across_host_tz(any_file: Path):
    results = {
        tz: _with_tz(tz, lambda: resolve(any_file, VIDEO_RAW, "America/Detroit",
                                         is_video=True).dt)
        for tz in HOST_TZS
    }
    assert len(set(results.values())) == 1
    # Late-night UTC lands on the previous LOCAL calendar day.
    assert next(iter(results.values())).date().isoformat() == "2024-06-15"


def test_target_dir_identical_across_host_tz(tmp_path: Path):
    dt = datetime(2024, 6, 15, 23, 59, 58)
    dirs = {
        tz: _with_tz(tz, lambda: _target_dir(tmp_path, dt, "Peepaw Cell"))
        for tz in HOST_TZS
    }
    assert len(set(map(str, dirs.values()))) == 1
    assert "06152024 - Unsorted" in str(next(iter(dirs.values())))
