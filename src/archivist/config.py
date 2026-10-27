"""Configuration loading and the source map."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_NAMES = ("config.yaml", "config.yml")
# 005 tunables. Justified against measured per-source rates in research.md R7:
# the busiest library adds ~400 items/month, so 500 clears a month of it. An
# undersized bound is self-reporting (FR-023), never silently lossy, so the
# default deliberately errs high.
DEFAULT_SCAN_BOUND = 500
DEFAULT_RECONCILE_INTERVAL_DAYS = 30
SMALL_SCAN_BOUND_WARN = 50
# Whether a routine refresh may escalate a stale source to a full sweep on
# its own. False means sweeps are operator-scheduled; the run still REPORTS
# which sources are overdue, so turning this off cannot hide a growing gap.
DEFAULT_AUTO_RECONCILE = True
ENV_CONFIG = "ARCHIVIST_CONFIG"
SENTINEL_NAME = ".archivist-volume-id"
USER_CONFIG_DIR = Path.home() / ".config" / "archivist"


@dataclass(frozen=True)
class Source:
    key: str
    type: str  # icloud | takeout | device | drop
    device_folder: str
    username: str | None = None  # Apple ID, for type=icloud
    # 005: per-source overrides. None means "use the config default".
    scan_bound: int | None = None            # items a routine refresh examines
    reconcile_interval_days: int | None = None  # staleness before a full sweep


@dataclass(frozen=True)
class Config:
    archive_root: Path
    work_root: Path  # the mount point (sentinel + guard live here)
    default_timezone: str
    work_subdir: str = "TheArchivist"  # all working files live under work_root/work_subdir
    sources: dict[str, Source] = field(default_factory=dict)
    path: Path | None = None
    # 005 defaults, overridable per source. See contracts/config-schema.md.
    scan_bound: int = DEFAULT_SCAN_BOUND
    reconcile_interval_days: int = DEFAULT_RECONCILE_INTERVAL_DAYS
    auto_reconcile: bool = DEFAULT_AUTO_RECONCILE

    def scan_bound_for(self, source_key: str) -> int:
        src = self.sources.get(source_key)
        if src is not None and src.scan_bound is not None:
            return src.scan_bound
        return self.scan_bound

    def reconcile_interval_for(self, source_key: str) -> int:
        src = self.sources.get(source_key)
        if src is not None and src.reconcile_interval_days is not None:
            return src.reconcile_interval_days
        return self.reconcile_interval_days

    @property
    def work_base(self) -> Path:
        """The tool's working directory: a subfolder of the mount, not its root."""
        return self.work_root / self.work_subdir

    # Derived working-directory layout (all under work_base).
    @property
    def staging_dir(self) -> Path:
        return self.work_base / "staging"

    @property
    def drops_dir(self) -> Path:
        return self.work_base / "drops"

    @property
    def logs_dir(self) -> Path:
        return self.work_base / "logs"

    @property
    def catalog_dir(self) -> Path:
        return self.work_base / "catalog"

    @property
    def catalog_db(self) -> Path:
        return self.catalog_dir / "archivist.sqlite3"

    @property
    def icloud_dir(self) -> Path:
        """Persistent iCloud download mirror (per-source subdirs)."""
        return self.staging_dir / "icloud"

    @property
    def icloud_session_dir(self) -> Path:
        """icloudpd cookie/session storage."""
        return self.work_base / "icloud-session"

    def pull_journal_path(self, run_id: str) -> Path:
        """Append-only coverage journal for one applying pull run (005 FR-007).

        Authoritative record of what each watermark advance claimed; the
        catalog's `coverage:<source>` key is a fast-read mirror of the latest
        entry, not the system of record (constitution Principle IV).
        """
        return self.logs_dir / f"pull-{run_id}.jsonl"


class ConfigError(Exception):
    pass


def validate_roots(config: "Config") -> list[str]:
    """Host-aware sanity check of the configured volume roots (FR-007, 004).

    Returns actionable error strings (empty list = OK). Detects config files
    carried between hosts unchanged — e.g. a Mac-style `/Volumes/...` path on
    a Linux guest — before any operation begins.
    """
    import sys

    errors: list[str] = []
    is_macos = sys.platform == "darwin"
    for label, path in (("archive_root", config.archive_root),
                        ("work_root", config.work_root)):
        if path.is_dir():
            continue
        msg = f"{label} does not exist on this host: {path}"
        if not is_macos and str(path).startswith("/Volumes/"):
            msg += (" — this is a macOS-style mount path; on Linux, point it at"
                    " the mounted share (e.g. /mnt/archive) in this host's config.yaml")
        elif is_macos and str(path).startswith(("/mnt/", "/srv/")):
            msg += (" — this is a Linux-style mount path; on macOS, point it at"
                    " the mounted volume (e.g. /Volumes/...) in this host's config.yaml")
        else:
            msg += " — is the share mounted, and is this the right config for this host?"
        errors.append(msg)
    return errors


def find_config(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the config path: explicit flag > env var > ./config.yaml."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise ConfigError(f"Config file not found: {p}")
        return p
    env = os.environ.get(ENV_CONFIG)
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise ConfigError(f"$%s points to a missing file: %s" % (ENV_CONFIG, p))
        return p
    # Discovery order after explicit/env: current dir, then ~/.config/archivist/.
    for name in DEFAULT_CONFIG_NAMES:
        p = Path.cwd() / name
        if p.is_file():
            return p
    for name in DEFAULT_CONFIG_NAMES:
        p = USER_CONFIG_DIR / name
        if p.is_file():
            return p
    raise ConfigError(
        "No config found. Create ./config.yaml or "
        f"{USER_CONFIG_DIR / 'config.yaml'} (see config.example.yaml), "
        f"or set ${ENV_CONFIG}."
    )


def load_config(explicit: str | os.PathLike[str] | None = None) -> Config:
    path = find_config(explicit)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    try:
        archive_root = Path(str(raw["archive_root"])).expanduser()
        work_root = Path(str(raw["work_root"])).expanduser()
    except KeyError as exc:
        raise ConfigError(f"Missing required key: {exc.args[0]}") from exc

    default_timezone = str(raw.get("default_timezone", "America/Detroit"))
    work_subdir = str(raw.get("work_subdir", "TheArchivist")).strip("/")

    scan_bound = _positive_int(raw, "scan_bound", DEFAULT_SCAN_BOUND, "top level")
    reconcile_interval_days = _positive_int(
        raw, "reconcile_interval_days", DEFAULT_RECONCILE_INTERVAL_DAYS, "top level")
    auto_reconcile = raw.get("auto_reconcile", DEFAULT_AUTO_RECONCILE)
    if not isinstance(auto_reconcile, bool):
        raise ConfigError(
            f"top level: 'auto_reconcile' must be true or false, got {auto_reconcile!r}")

    sources: dict[str, Source] = {}
    for key, val in (raw.get("sources") or {}).items():
        if not isinstance(val, dict):
            raise ConfigError(f"Source '{key}' must be a mapping")
        try:
            stype = str(val["type"])
            # The 005 tunables mean nothing outside an icloud source; silently
            # ignoring one would hide a typo in a key that governs coverage.
            for tunable in ("scan_bound", "reconcile_interval_days"):
                if tunable in val and stype != "icloud":
                    raise ConfigError(
                        f"Source '{key}' is type '{stype}' — '{tunable}' only "
                        f"applies to icloud sources"
                    )
            sources[key] = Source(
                key=key,
                type=stype,
                device_folder=str(val["device_folder"]),
                username=(str(val["username"]) if val.get("username") else None),
                scan_bound=_positive_int(val, "scan_bound", None, f"source '{key}'"),
                reconcile_interval_days=_positive_int(
                    val, "reconcile_interval_days", None, f"source '{key}'"),
            )
        except KeyError as exc:
            raise ConfigError(
                f"Source '{key}' missing key: {exc.args[0]}"
            ) from exc

    return Config(
        archive_root=archive_root,
        work_root=work_root,
        default_timezone=default_timezone,
        work_subdir=work_subdir,
        sources=sources,
        path=path,
        scan_bound=scan_bound,
        reconcile_interval_days=reconcile_interval_days,
        auto_reconcile=auto_reconcile,
    )


def _positive_int(mapping: dict, key: str, default, where: str) -> int | None:
    """Read an optional positive-int setting, refusing junk at load time.

    Config errors surface before any volume is touched, so a typo in a coverage
    tunable can never reach a run.
    """
    if key not in mapping or mapping[key] is None:
        return default
    val = mapping[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ConfigError(f"{where}: '{key}' must be a whole number, got {val!r}")
    if val < 1:
        raise ConfigError(f"{where}: '{key}' must be >= 1, got {val}")
    return val


def small_scan_bound_warnings(config: "Config") -> list[str]:
    """Sources whose scan bound is small enough that refusals are likely.

    Accepted, not refused: the operator may know their library is tiny. FR-023
    makes the consequence visible either way.
    """
    out = []
    for key, src in config.sources.items():
        if src.type != "icloud":
            continue
        bound = config.scan_bound_for(key)
        if bound < SMALL_SCAN_BOUND_WARN:
            out.append(
                f"source '{key}': scan_bound {bound} is small — routine runs "
                f"may refuse to advance coverage (raise it if that happens)")
    return out
