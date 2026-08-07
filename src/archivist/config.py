"""Configuration loading and the source map."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_NAMES = ("config.yaml", "config.yml")
ENV_CONFIG = "ARCHIVIST_CONFIG"
SENTINEL_NAME = ".archivist-volume-id"
USER_CONFIG_DIR = Path.home() / ".config" / "archivist"


@dataclass(frozen=True)
class Source:
    key: str
    type: str  # icloud | takeout | device | drop
    device_folder: str
    username: str | None = None  # Apple ID, for type=icloud


@dataclass(frozen=True)
class Config:
    archive_root: Path
    work_root: Path  # the mount point (sentinel + guard live here)
    default_timezone: str
    work_subdir: str = "TheArchivist"  # all working files live under work_root/work_subdir
    sources: dict[str, Source] = field(default_factory=dict)
    path: Path | None = None

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

    sources: dict[str, Source] = {}
    for key, val in (raw.get("sources") or {}).items():
        if not isinstance(val, dict):
            raise ConfigError(f"Source '{key}' must be a mapping")
        try:
            sources[key] = Source(
                key=key,
                type=str(val["type"]),
                device_folder=str(val["device_folder"]),
                username=(str(val["username"]) if val.get("username") else None),
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
    )
