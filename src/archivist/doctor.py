"""Environment health checks: `archivist doctor` (feature 004).

Provisioning-time diagnostics for any host (macOS or Linux). Read-only —
deliberately usable on a half-provisioned machine; that is its job.

A check is *required* only when the configuration demands it: icloudpd and
the keyring probe are required only if at least one `icloud` source is
configured. Config validity, volumes, exiftool, ffmpeg/ffprobe, HEIC
support, and timezone resolution are always required.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .config import Config, validate_roots
from .guard import check_volumes

WORK_BUDGET_BYTES = 50 * 1024**3  # ~50 GB working-storage budget (FR-015)

_KEYRING_SERVICE = "archivist-doctor-probe"


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    detail: str
    remedy: str | None = None


def _version_of(exe: str, args: list[str]) -> str | None:
    if shutil.which(exe) is None:
        return None
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=15)
        line = (proc.stdout or proc.stderr).strip().splitlines()
        return line[0][:70] if line else "present"
    except Exception:
        return "present (version query failed)"


def probe_keyring() -> tuple[bool, str]:
    """True if a functional SECURE keyring backend exists on this host.

    Performs a real set/get/delete round-trip and rejects known-insecure
    backends (plaintext/chainer-to-nothing). Never stores anything but a
    throwaway token.
    """
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
    except Exception as exc:  # pragma: no cover - packaging problem
        return False, f"python-keyring unavailable: {exc}"
    backend = keyring.get_keyring()
    name = f"{type(backend).__module__}.{type(backend).__name__}"
    if isinstance(backend, FailKeyring) or "fail" in name.lower():
        return False, f"no functional backend ({name})"
    if "plaintext" in name.lower() or "keyrings.alt" in name.lower():
        return False, f"backend is not secure ({name}) — refusing (FR-010)"
    token = uuid.uuid4().hex
    try:
        keyring.set_password(_KEYRING_SERVICE, "probe", token)
        ok = keyring.get_password(_KEYRING_SERVICE, "probe") == token
        keyring.delete_password(_KEYRING_SERVICE, "probe")
    except Exception as exc:
        return False, f"backend {name} failed round-trip: {exc}"
    return ok, name


def _dir_usage(path) -> int:
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


def run_checks(cfg: Config) -> list[Check]:
    checks: list[Check] = []
    has_icloud = any(s.type == "icloud" for s in cfg.sources.values())

    # Config roots on THIS host (FR-007).
    root_errors = validate_roots(cfg)
    checks.append(Check(
        "config-roots", not root_errors, True,
        "; ".join(root_errors) if root_errors else "archive_root and work_root exist",
        remedy="fix the paths in this host's config.yaml" if root_errors else None,
    ))

    # Volume guard (read-only view).
    vols = check_volumes(cfg)
    bad = [v for v in vols if not v.ok]
    checks.append(Check(
        "volumes", not bad, True,
        ", ".join(f"{v.label}={'OK' if v.ok else 'FAIL'}" for v in vols),
        remedy="mount the shares and run `archivist init-volumes`" if bad else None,
    ))

    # Required executables.
    for exe, args in (("exiftool", ["-ver"]), ("ffmpeg", ["-version"]),
                      ("ffprobe", ["-version"])):
        ver = _version_of(exe, args)
        checks.append(Check(
            exe, ver is not None, True, ver or "not found on PATH",
            remedy=f"install {exe}" if ver is None else None,
        ))

    # icloudpd + keyring: required only when an icloud source is configured.
    ver = _version_of("icloudpd", ["--version"])
    checks.append(Check(
        "icloudpd", ver is not None, has_icloud, ver or "not found on PATH",
        remedy="uv tool install icloudpd" if ver is None else None,
    ))
    kr_ok, kr_detail = probe_keyring()
    checks.append(Check(
        "keyring", kr_ok, has_icloud, kr_detail,
        remedy=("provision a secure keyring (macOS Keychain / gnome-keyring "
                "via Secret Service — see docs/linux-host.md §2)") if not kr_ok else None,
    ))

    # HEIC support.
    try:
        import pillow_heif  # noqa: F401
        checks.append(Check("heic-support", True, True,
                            f"pillow-heif {pillow_heif.__version__}"))
    except Exception as exc:
        checks.append(Check("heic-support", False, True, str(exc),
                            remedy="uv sync (pillow-heif is a dependency)"))

    # Configured timezone resolves (host TZ is irrelevant to filing, FR-008).
    try:
        ZoneInfo(cfg.default_timezone)
        checks.append(Check("timezone", True, True,
                            f"{cfg.default_timezone} resolves (host TZ irrelevant to filing)"))
    except Exception as exc:
        checks.append(Check("timezone", False, True,
                            f"{cfg.default_timezone}: {exc}",
                            remedy="fix default_timezone in config.yaml"))

    # Working-storage usage vs budget (informational unless over budget).
    used = _dir_usage(cfg.work_base)
    over = used > WORK_BUDGET_BYTES
    checks.append(Check(
        "work-storage", not over, False,
        f"{used / 1024**3:.1f} GB used of ~{WORK_BUDGET_BYTES / 1024**3:.0f} GB budget",
        remedy="run `archivist prune-staging` to reclaim verified staging" if over else None,
    ))

    return checks
