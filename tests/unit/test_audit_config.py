"""Unit tests: the 006 settings and the audit interval."""

from datetime import datetime, timedelta

import pytest
import yaml

from archivist.audit import is_audit_due
from archivist.config import (DEFAULT_AUDIT_INTERVAL_DAYS, DEFAULT_AUTO_REPAIR,
                              DEFAULT_REPAIR_BUDGET_GB, ConfigError, load_config)

NOW = datetime(2026, 10, 27, 12, 0, 0)


def write(tmp_path, **extra):
    raw = {
        "archive_root": str(tmp_path / "archive"),
        "work_root": str(tmp_path / "work"),
        "default_timezone": "America/Detroit",
        "sources": {"kat": {"type": "icloud", "device_folder": "Kat Cell",
                            "username": "k@example.com"}},
    }
    raw.update(extra)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw))
    return load_config(p)


def test_defaults(tmp_path):
    cfg = write(tmp_path)
    assert cfg.audit_interval_days == DEFAULT_AUDIT_INTERVAL_DAYS == 7
    assert cfg.repair_budget_gb == DEFAULT_REPAIR_BUDGET_GB == 5.0
    assert cfg.auto_repair is DEFAULT_AUTO_REPAIR is True
    assert cfg.repair_budget_bytes_for("kat") == int(5 * 1024 ** 3)


def test_top_level_overrides(tmp_path):
    cfg = write(tmp_path, audit_interval_days=3, repair_budget_gb=1.5,
                auto_repair=False)
    assert cfg.audit_interval_for("kat") == 3
    assert cfg.repair_budget_bytes_for("kat") == int(1.5 * 1024 ** 3)
    assert cfg.auto_repair is False


def test_per_source_overrides_win(tmp_path):
    cfg = write(tmp_path, audit_interval_days=7, sources={
        "kat": {"type": "icloud", "device_folder": "Kat Cell",
                "username": "k@example.com",
                "audit_interval_days": 1, "repair_budget_gb": 20},
    })
    assert cfg.audit_interval_for("kat") == 1
    assert cfg.repair_budget_bytes_for("kat") == 20 * 1024 ** 3


@pytest.mark.parametrize("bad", [0, -1, "weekly"])
def test_non_positive_interval_refused(tmp_path, bad):
    with pytest.raises(ConfigError):
        write(tmp_path, audit_interval_days=bad)


@pytest.mark.parametrize("bad", [0, -2.5, "lots"])
def test_non_positive_budget_refused(tmp_path, bad):
    with pytest.raises(ConfigError):
        write(tmp_path, repair_budget_gb=bad)


def test_non_boolean_auto_repair_refused(tmp_path):
    with pytest.raises(ConfigError):
        write(tmp_path, auto_repair="yes")


def test_tunables_rejected_on_non_icloud_sources(tmp_path):
    """A typo in a key that governs coverage must not be silently ignored."""
    with pytest.raises(ConfigError, match="only applies to icloud"):
        write(tmp_path, sources={
            "drops": {"type": "drop", "device_folder": "Misc",
                      "audit_interval_days": 3},
        })


# --- the interval ----------------------------------------------------------

def test_never_audited_is_due():
    assert is_audit_due(None, NOW, 7)


def test_unreadable_timestamp_is_due():
    """Unparseable state means we cannot tell, so we look again."""
    assert is_audit_due("last tuesday", NOW, 7)


def test_inside_the_interval_is_not_due():
    assert not is_audit_due((NOW - timedelta(days=3)).isoformat(), NOW, 7)


def test_exactly_at_the_interval_is_due():
    assert is_audit_due((NOW - timedelta(days=7)).isoformat(), NOW, 7)


def test_past_the_interval_is_due():
    assert is_audit_due((NOW - timedelta(days=30)).isoformat(), NOW, 7)
