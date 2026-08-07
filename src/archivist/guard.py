"""Volume / sentinel guard.

Defends against the SMB/NFS failure mode where an unmounted share leaves an
empty but writable local mount-point directory. We refuse to operate unless the
expected volume is present AND carries its `.archivist-volume-id` sentinel.

`check_volumes` is read-only and used by `status`. `require_volumes` raises and
is called by any mutating command before it touches the filesystem.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Config, SENTINEL_NAME


@dataclass(frozen=True)
class VolumeStatus:
    label: str
    path: Path
    exists: bool          # mount-point path exists
    is_dir: bool
    writable: bool
    sentinel: bool        # sentinel file present
    sentinel_id: str | None

    @property
    def ok(self) -> bool:
        return self.exists and self.is_dir and self.writable and self.sentinel


class GuardError(Exception):
    pass


def _status(label: str, path: Path) -> VolumeStatus:
    exists = path.exists()
    is_dir = path.is_dir()
    writable = is_dir and os.access(path, os.W_OK)
    sentinel_path = path / SENTINEL_NAME
    sentinel = sentinel_path.is_file()
    sentinel_id = None
    if sentinel:
        try:
            sentinel_id = sentinel_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            sentinel_id = None
    return VolumeStatus(
        label=label,
        path=path,
        exists=exists,
        is_dir=is_dir,
        writable=writable,
        sentinel=sentinel,
        sentinel_id=sentinel_id,
    )


def check_volumes(config: Config) -> list[VolumeStatus]:
    """Read-only report on both required mounts."""
    return [
        _status("archive_root", config.archive_root),
        _status("work_root", config.work_root),
    ]


def require_volumes(config: Config) -> list[VolumeStatus]:
    """Raise GuardError unless both mounts are present, writable, and sentinelled."""
    statuses = check_volumes(config)
    bad = [s for s in statuses if not s.ok]
    if bad:
        lines = ["Refusing to run — volume guard failed:"]
        for s in bad:
            reason = (
                "missing mount-point" if not s.exists
                else "not a directory" if not s.is_dir
                else "not writable" if not s.writable
                else f"missing sentinel '{SENTINEL_NAME}' (is the share mounted?)"
            )
            lines.append(f"  - {s.label} ({s.path}): {reason}")
        lines.append("Run `archivist init-volumes` once the correct shares are mounted.")
        raise GuardError("\n".join(lines))
    return statuses


def init_volume(path: Path) -> tuple[str, bool]:
    """Write a sentinel id to `path` if absent. Returns (id, created)."""
    sentinel_path = path / SENTINEL_NAME
    if sentinel_path.is_file():
        existing = sentinel_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing, False
    new_id = uuid.uuid4().hex
    sentinel_path.write_text(new_id + "\n", encoding="utf-8")
    return new_id, True
