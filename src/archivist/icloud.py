"""iCloud integration via icloudpd.

icloudpd downloads into a PERSISTENT per-source mirror on the work drive (it
skips already-downloaded files, so repeat pulls are incremental). The Phase 2
ingest engine then copies new media from the mirror into the archive. icloudpd
never writes to the archive, and we never pass --auto-delete, so the iCloud
source is never modified.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


class ICloudError(Exception):
    pass


# Overlap subtracted from the stored pull state when computing the routine
# window (FR-015). Absorbs clock skew and late-arriving cloud items; catalog
# dedup makes re-downloaded overlap harmless (zero re-filing).
WINDOW_OVERLAP_DAYS = 7


def pull_state_key(source_key: str) -> str:
    return f"pull_state:{source_key}"


def window_since(last_pull_iso: str) -> str:
    """The --skip-created-before date for a routine windowed pull."""
    last = datetime.fromisoformat(last_pull_iso)
    return (last - timedelta(days=WINDOW_OVERLAP_DAYS)).strftime("%Y-%m-%d")


def icloudpd_available() -> bool:
    return shutil.which("icloudpd") is not None


def _base_cmd(username: str, mirror: Path, session_dir: Path) -> list[str]:
    return [
        "icloudpd",
        "--username", username,
        "--directory", str(mirror),
        "--cookie-directory", str(session_dir),
        "--domain", "com",
    ]


def auth(username: str, session_dir: Path) -> int:
    """Interactive one-time auth: establishes the session and stores the password
    in the system keyring. Inherits the terminal so the user can enter password +
    2FA code. Returns the icloudpd exit code.
    """
    if not icloudpd_available():
        raise ICloudError("icloudpd not found on PATH (uv tool install icloudpd)")
    session_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "icloudpd",
        "--username", username,
        "--cookie-directory", str(session_dir),
        "--domain", "com",
        "--auth-only",
        # Providers are checked in order, one flag per provider: keyring first
        # (so re-auth never re-prompts), console fallback (first-time prompt;
        # icloudpd persists a console-entered password into the keyring).
        "--password-provider", "keyring",
        "--password-provider", "console",
    ]
    rc = subprocess.run(cmd).returncode
    # icloudpd can exit 0 without doing anything (e.g. argument mishaps), so
    # trust the cookie on disk, not the exit code alone.
    if rc == 0 and not session_established(session_dir):
        raise ICloudError(
            "icloudpd exited 0 but no session cookie was written to "
            f"{session_dir} — authentication did not complete."
        )
    return rc


def session_established(session_dir: Path) -> bool:
    """True if at least one cookie/session file exists in the cookie dir."""
    return session_dir.is_dir() and any(
        p.is_file() and not p.name.startswith(".") for p in session_dir.iterdir()
    )


def download(username: str, mirror: Path, session_dir: Path,
             recent: int | None = None, until_found: int | None = None,
             since: str | None = None, until: str | None = None,
             dry_run: bool = False) -> int:
    """Run icloudpd to mirror the library (or a recent window) into `mirror`.

    Non-interactive: uses the keyring password + stored cookie. If the session
    has expired, icloudpd exits non-zero and the caller should tell the user to
    re-run `archivist auth icloud`.

      recent       -> download only the N most recent items
      since         -> skip items created before this date (YYYY-MM-DD)
      until_found  -> stop after N consecutive already-downloaded items (incremental)
      dry_run      -> icloudpd's native --dry-run (touches nothing)
    """
    if not icloudpd_available():
        raise ICloudError("icloudpd not found on PATH (uv tool install icloudpd)")
    mirror.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    cmd = _base_cmd(username, mirror, session_dir) + [
        "--password-provider", "keyring",
        "--size", "original",
        "--live-photo-size", "original",
        # Same base name for the Live Photo MOV so our grouping pairs HEIC+MOV.
        "--live-photo-mov-filename-policy", "original",
        "--folder-structure", "{:%Y/%m}",
        "--no-progress-bar",
    ]
    if recent is not None:
        cmd += ["--recent", str(recent)]
    if since:
        cmd += ["--skip-created-before", since]
    if until:
        cmd += ["--skip-created-after", until]
    if until_found is not None:
        cmd += ["--until-found", str(until_found)]
    if dry_run:
        cmd += ["--dry-run"]
    return subprocess.run(cmd).returncode
