"""Unit tests: scan_bound / reconcile_interval_days config (005, contracts §1/§3)."""

import pytest
import yaml

from archivist.config import (DEFAULT_RECONCILE_INTERVAL_DAYS, DEFAULT_SCAN_BOUND,
                              ConfigError, load_config, small_scan_bound_warnings)

BASE = {
    "archive_root": "/tmp/archive",
    "work_root": "/tmp/work",
    "default_timezone": "America/Detroit",
}


def write(tmp_path, **extra):
    payload = {**BASE, **extra}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def icloud_src(**kw):
    return {"type": "icloud", "device_folder": "A Cell",
            "username": "a@example.com", **kw}


def test_defaults_when_absent(tmp_path):
    cfg = load_config(write(tmp_path, sources={"a": icloud_src()}))
    assert cfg.scan_bound_for("a") == DEFAULT_SCAN_BOUND == 500
    assert cfg.reconcile_interval_for("a") == DEFAULT_RECONCILE_INTERVAL_DAYS == 30


def test_top_level_override(tmp_path):
    cfg = load_config(write(tmp_path, scan_bound=250, reconcile_interval_days=14,
                            sources={"a": icloud_src()}))
    assert cfg.scan_bound_for("a") == 250
    assert cfg.reconcile_interval_for("a") == 14


def test_per_source_beats_top_level(tmp_path):
    cfg = load_config(write(tmp_path, scan_bound=250,
                            sources={"a": icloud_src(scan_bound=1500),
                                     "b": icloud_src()}))
    assert cfg.scan_bound_for("a") == 1500
    assert cfg.scan_bound_for("b") == 250


def test_unknown_source_falls_back_to_the_default(tmp_path):
    cfg = load_config(write(tmp_path, sources={"a": icloud_src()}))
    assert cfg.scan_bound_for("nonexistent") == DEFAULT_SCAN_BOUND


@pytest.mark.parametrize("bad", [0, -1, -500])
def test_non_positive_is_refused(tmp_path, bad):
    with pytest.raises(ConfigError, match=">= 1"):
        load_config(write(tmp_path, sources={"a": icloud_src(scan_bound=bad)}))


@pytest.mark.parametrize("bad", ["500", 1.5, True])
def test_non_integer_is_refused(tmp_path, bad):
    with pytest.raises(ConfigError, match="whole number"):
        load_config(write(tmp_path, sources={"a": icloud_src(scan_bound=bad)}))


def test_tunable_on_a_non_icloud_source_is_refused(tmp_path):
    """Silently ignoring it would hide a typo in a key that governs coverage."""
    with pytest.raises(ConfigError, match="only applies to icloud"):
        load_config(write(tmp_path, sources={
            "d": {"type": "drop", "device_folder": "Drop", "scan_bound": 100}}))


def test_bad_top_level_value_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="top level"):
        load_config(write(tmp_path, scan_bound=0, sources={"a": icloud_src()}))


def test_small_bound_warns_but_is_accepted(tmp_path):
    cfg = load_config(write(tmp_path, sources={"a": icloud_src(scan_bound=10)}))
    warnings = small_scan_bound_warnings(cfg)
    assert len(warnings) == 1 and "scan_bound 10 is small" in warnings[0]


def test_healthy_bound_does_not_warn(tmp_path):
    cfg = load_config(write(tmp_path, sources={"a": icloud_src()}))
    assert small_scan_bound_warnings(cfg) == []


def test_existing_configs_remain_valid(tmp_path):
    """No migration: a config written before 005 must load unchanged."""
    cfg = load_config(write(tmp_path, sources={
        "a": icloud_src(), "d": {"type": "drop", "device_folder": "Drop"}}))
    assert set(cfg.sources) == {"a", "d"}
    assert cfg.scan_bound == DEFAULT_SCAN_BOUND
