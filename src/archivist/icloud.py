"""iCloud integration via icloudpd.

icloudpd downloads into a TRANSIENT per-source mirror on the work drive. The
mirror is pass-through storage only: media lands there on its way to the
archive and `prune-staging` may reclaim it at any time once the archived copy
is byte-verified (feature 004). Nothing here may treat mirror contents as a
record of what has been downloaded, or as evidence that a window was covered.
icloudpd never writes to the archive, and we never pass --auto-delete or
--delete-after-download, so the iCloud source is never modified.

Coverage is PROVEN, not inferred (005 FR-002). The downloader's exit status
tells us whether the process crashed, not whether it covered the window it was
asked for, so `download()` captures icloudpd's own output and parses it into a
`CoverageProof`. Anything the parser cannot positively confirm fails closed:
the caller refuses to advance a watermark and says why. An upstream rewording
therefore degrades to noisy refusals, never to silent loss.
"""

from __future__ import annotations

import http.cookiejar
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable


class ICloudError(Exception):
    pass


# Overlap subtracted from the stored pull state when computing the routine
# window (FR-015). Absorbs clock skew and late-arriving cloud items; catalog
# dedup makes re-downloaded overlap harmless (zero re-filing).
WINDOW_OVERLAP_DAYS = 7

# Defaults for the two 005 settings; config may override per source.
DEFAULT_SCAN_BOUND = 500
DEFAULT_RECONCILE_INTERVAL_DAYS = 30

# icloudpd versions whose log vocabulary this parser has been checked against.
# The strings below are not a stable upstream API, so an unrecognised version
# is refused rather than trusted (contracts/coverage-proof.md §3.1).
TESTED_ICLOUDPD_VERSIONS = frozenset({"1.32.3"})


def pull_state_key(source_key: str) -> str:
    return f"pull_state:{source_key}"


def reconcile_state_key(source_key: str) -> str:
    return f"reconcile_state:{source_key}"


def coverage_key(source_key: str) -> str:
    return f"coverage:{source_key}"


def window_since(last_pull_iso: str) -> str:
    """The --skip-created-before date for a routine windowed pull."""
    last = datetime.fromisoformat(last_pull_iso)
    return (last - timedelta(days=WINDOW_OVERLAP_DAYS)).strftime("%Y-%m-%d")


def is_reconcile_due(reconciled_through: str | None, now: datetime,
                     interval_days: int = DEFAULT_RECONCILE_INTERVAL_DAYS) -> bool:
    """True when this source is owed a complete unbounded sweep (FR-012/FR-016).

    An absent watermark is due: a source that has never been reconciled is
    exactly the case reconciliation exists to repair.
    """
    if not reconciled_through:
        return True
    try:
        last = datetime.fromisoformat(reconciled_through)
    except ValueError:
        return True          # unparseable state is not evidence of freshness
    return (now - last) > timedelta(days=interval_days)


def icloudpd_available() -> bool:
    return shutil.which("icloudpd") is not None


_RE_VERSION = re.compile(r"version:\s*([0-9]+\.[0-9]+\.[0-9]+)")


def probe_version() -> str | None:
    """The installed icloudpd version, or None if it cannot be determined."""
    if not icloudpd_available():
        return None
    try:
        out = subprocess.run(["icloudpd", "--version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _RE_VERSION.search((out.stdout or "") + (out.stderr or ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Coverage proof
# ---------------------------------------------------------------------------

# Signals, per contracts/coverage-proof.md §2. The skip line and the completion
# line are transcribed from real icloudpd 1.32.3 output; the rest follow the
# upstream source. Matching is deliberately loose on the parts that vary
# (filenames, paths, timestamps) and strict on the parts that carry meaning.
_RE_COMPLETE = re.compile(
    r"All (?:photos and videos|photos|videos) have been downloaded")
_RE_SKIP_BEFORE = re.compile(r"Skipping .+?, as it was created .+?, before .+")
_RE_SKIP_AFTER = re.compile(r"Skipping .+?, as it was created .+?, after .+")
_RE_UNTIL_FOUND = re.compile(
    r"Found \d+ consecutive previously downloaded photos\. Exiting")
# Verbatim upstream v1.32.3 format strings (src/icloudpd/base.py):
#   "%s already exists"                 -- no trailing period
#   "Downloaded %s"                     -- PAST tense, one per item downloaded
#   "Downloading %s %s %s to %s ..."    -- one-off preamble, where the first %s
#                                          is "the first" only when the count is
#                                          1, otherwise the number, otherwise "???"
# Getting any of these subtly wrong is silent: the parser still "works", it just
# counts the wrong things. Every one of them is pinned by a fixture transcribing
# the real wording, in both its singular and plural forms.
#: icloudpd logs this at INFO *before* it calls input() for the code, so it is
#: a clean place to intervene. Verbatim from upstream authentication.py:
#:   logger.info("Two-factor authentication is required (2fa)")
#:   logger.info("Two-step authentication is required (2sa)")
_RE_MFA_REQUIRED = re.compile(r"Two-(?:factor|step) authentication is required")
_RE_ALREADY = re.compile(r"already exists\b")
_RE_DOWNLOADED_ITEM = re.compile(r"\bDownloaded\b")
_RE_DOWNLOAD_PREAMBLE = re.compile(
    r"Downloading (?:the first|\d+|\?\?\?) .* to .*\.\.\.")
# Tolerated fallback: a per-item line phrased in the present tense, which is
# what older builds emit. Never allowed to match the preamble above.
_RE_DOWNLOADING = re.compile(r"\bDownloading\b")


@dataclass(frozen=True)
class CoverageProof:
    """What the download step demonstrably did — the basis for any advance.

    `parser_confident` False means "we could not confirm this run", and no
    watermark may move on it. That is the safe direction: a stale watermark
    re-covers ground, a premature one loses it.
    """

    enumeration_complete: bool = False
    reached_before_cutoff: bool = False
    until_found_exit: bool = False
    examined: int = 0
    downloaded: int = 0
    already_present: int = 0
    exit_code: int = 0
    session_present_before: bool = False
    parser_confident: bool = False
    notes: tuple[str, ...] = ()

    def note_text(self) -> str:
        return "; ".join(self.notes) if self.notes else "no detail recorded"


class StreamTally:
    """Accumulates icloudpd signals as lines arrive (streaming, not buffered)."""

    def __init__(self) -> None:
        self.complete = False
        self.mfa_required = False
        self.skip_before = 0
        self.skip_after = 0
        self.until_found_exit = False
        # Counted separately: icloudpd emits BOTH a present-tense and a
        # past-tense line per item, so summing them double-counts. Observed on
        # a real 33,124-file sweep that reported 66,224 downloads.
        self._downloaded_past = 0
        self._downloaded_present = 0
        self.already_present = 0

    def feed(self, line: str) -> None:
        if _RE_MFA_REQUIRED.search(line):
            self.mfa_required = True
            return
        if _RE_COMPLETE.search(line):
            self.complete = True
            return
        if _RE_UNTIL_FOUND.search(line):
            self.until_found_exit = True
            return
        if _RE_SKIP_BEFORE.search(line):
            self.skip_before += 1
            return
        if _RE_SKIP_AFTER.search(line):
            self.skip_after += 1
            return
        if _RE_ALREADY.search(line):
            self.already_present += 1
            return
        if _RE_DOWNLOAD_PREAMBLE.search(line):
            return                      # one-off banner, not an item
        if _RE_DOWNLOADED_ITEM.search(line):
            self._downloaded_past += 1
            return
        if _RE_DOWNLOADING.search(line):
            self._downloaded_present += 1

    @property
    def downloaded(self) -> int:
        """One count per item, never the sum of both phrasings.

        Current icloudpd logs the present tense as it starts an item and the
        past tense when it finishes, so the past-tense count is authoritative
        whenever it appears. The present-tense count is the fallback for builds
        that only emit that form.
        """
        return self._downloaded_past or self._downloaded_present

    @property
    def examined(self) -> int:
        """Lower bound on what the downloader considered. Reporting only."""
        return (self.downloaded + self.already_present
                + self.skip_before + self.skip_after)


def build_proof(tally: StreamTally, *, exit_code: int,
                session_present_before: bool, version: str | None,
                truncated: bool = False,
                session_detail: str = "") -> CoverageProof:
    """Apply the fail-closed rules of contracts/coverage-proof.md §3.1."""
    notes: list[str] = []

    if not session_present_before:
        notes.append("no usable session artifact before the run"
                     + (f": {session_detail}" if session_detail else ""))
    if version is None:
        notes.append("icloudpd version could not be determined")
    elif version not in TESTED_ICLOUDPD_VERSIONS:
        notes.append(
            f"icloudpd {version} is not a version this parser has been checked "
            f"against (tested: {', '.join(sorted(TESTED_ICLOUDPD_VERSIONS))})")
    if exit_code != 0:
        notes.append(f"icloudpd exited {exit_code}")
    if truncated:
        notes.append("output stream ended mid-line")
    if tally.mfa_required:
        notes.append(
            "iCloud asked for a two-factor code, which this non-interactive "
            "path cannot answer — re-authenticate, then retry")
    elif not tally.complete and not tally.until_found_exit:
        notes.append("no completion signal in icloudpd output")

    return CoverageProof(
        enumeration_complete=tally.complete,
        reached_before_cutoff=tally.skip_before > 0,
        until_found_exit=tally.until_found_exit,
        examined=tally.examined,
        downloaded=tally.downloaded,
        already_present=tally.already_present,
        exit_code=exit_code,
        session_present_before=session_present_before,
        parser_confident=not notes,
        notes=tuple(notes),
    )


def parse_lines(lines: Iterable[str], *, exit_code: int = 0,
                session_present_before: bool = True,
                version: str | None = "1.32.3",
                truncated: bool = False) -> CoverageProof:
    """Convenience wrapper: parse a whole captured stream at once (tests)."""
    tally = StreamTally()
    for line in lines:
        tally.feed(line)
    return build_proof(tally, exit_code=exit_code,
                       session_present_before=session_present_before,
                       version=version, truncated=truncated)


# ---------------------------------------------------------------------------
# icloudpd invocation
# ---------------------------------------------------------------------------


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
        # INFO, not icloudpd's default of debug. At debug it dumps every HTTP
        # transaction, including the account's 2FA trust token in cleartext,
        # into the operator's scrollback. The download path still needs debug
        # (the skip-before and already-exists coverage signals are DEBUG lines);
        # auth parses nothing, so it has no reason to run that loud.
        "--log-level", "info",
        # Providers are checked in order, one flag per provider: keyring first
        # (so re-auth never re-prompts), console fallback (first-time prompt;
        # icloudpd persists a console-entered password into the keyring).
        "--password-provider", "keyring",
        "--password-provider", "console",
    ]
    rc = subprocess.run(cmd).returncode
    # icloudpd exits 0 even when the sign-in FAILED -- observed on an account
    # Apple had locked, where it logged the lockout and returned 0 anyway. So
    # the exit code cannot be the success signal, and neither can "a cookie
    # file appeared": the failed attempt rewrites the jar with the handshake
    # cookies. Require the post-login cookies for THIS account.
    if rc == 0:
        ok, why = session_status(session_dir, username)
        if not ok:
            raise ICloudError(
                f"authentication did not complete — {why}.\n"
                "Read icloudpd's messages above for the cause. If Apple "
                "reports the account is locked, unlock it at "
                "https://iforgot.apple.com before retrying — further attempts "
                "extend the lock rather than clearing it."
            )
    return rc


#: Cookies Apple writes only once a sign-in has COMPLETED. The pre-auth
#: handshake (aasp, acn01, dslang, site, X-APPLE-WEBAUTH-HSA-TRUST) is written
#: even when the sign-in subsequently FAILS, so the presence of a cookie file
#: proves nothing at all. Observed 2026-10-27 on an account Apple had locked:
#: icloudpd logged the lockout, exited 0, left a 7-cookie jar on disk, and the
#: old presence check reported "session established" in green -- which invited
#: the retries that deepened the lock.
_SESSION_PROOF_COOKIES = ("X-APPLE-WEBAUTH-TOKEN", "X-APPLE-WEBAUTH-USER")


def session_file_for(username: str) -> str:
    r"""icloudpd's own cookie-filename rule: drop every non-word character.

    Mirrors PyiCloudService, which derives the jar path from the username via
    ``[c for c in username if re.match(r"\w", c)]``. Kept in lockstep so a
    per-account check reads the very file icloudpd will use.
    """
    return "".join(c for c in username if c.isalnum() or c == "_")


def session_status(session_dir: Path, username: str) -> tuple[bool, str]:
    """Is THIS account's session usable? -> (ok, operator-facing reason).

    Entirely local and read-only. It makes no network call, so it can never
    trigger a sign-in attempt or a 2FA push, which matters: the thing it most
    needs to diagnose is an account that is locked precisely because of too
    many attempts. A check that had to phone Apple to answer would be the one
    check you cannot safely run.

    Accounts share one cookie directory, so this is deliberately per-username.
    The predecessor took only the directory and answered "yes" whenever ANY
    account had ever signed in.
    """
    jar_path = session_dir / session_file_for(username)
    if not jar_path.is_file():
        return False, f"no session file for {username}"
    jar = http.cookiejar.LWPCookieJar(str(jar_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:
        return False, (f"session file for {username} is unreadable "
                       f"({exc.__class__.__name__})")
    found = {c.name: c for c in jar if c.name in _SESSION_PROOF_COOKIES}
    missing = [n for n in _SESSION_PROOF_COOKIES if n not in found]
    if missing:
        return False, (f"sign-in never completed for {username} "
                       f"(no {missing[0]} in the session)")
    now = time.time()
    if any(c.expires and c.expires <= now for c in found.values()):
        return False, f"session for {username} has expired"
    return True, ""


def session_established(session_dir: Path, username: str | None = None) -> bool:
    """Per-account when given a username; otherwise the legacy presence check.

    The username-less form answers only "has anyone ever signed in here", which
    is not a question worth acting on. Production callers pass the username.
    """
    if username is not None:
        return session_status(session_dir, username)[0]
    return session_dir.is_dir() and any(
        p.is_file() and not p.name.startswith(".") for p in session_dir.iterdir()
    )


def build_download_cmd(username: str, mirror: Path, session_dir: Path, *,
                       recent: int | None = None, until_found: int | None = None,
                       since: str | None = None, until: str | None = None,
                       dry_run: bool = False) -> list[str]:
    """The exact argument list for a download run.

    Separated from execution so the safety test can assert, for every mode,
    that no iCloud-mutating flag is ever constructed (constitution Principle I).
    """
    cmd = _base_cmd(username, mirror, session_dir) + [
        "--password-provider", "keyring",
        "--size", "original",
        "--live-photo-size", "original",
        # Same base name for the Live Photo MOV so our grouping pairs HEIC+MOV.
        "--live-photo-mov-filename-policy", "original",
        "--folder-structure", "{:%Y/%m}",
        "--no-progress-bar",
        # Always debug: the per-item skip lines are the evidence that a bounded
        # scan cleared its window. Whether the OPERATOR sees them is a separate
        # decision, made by the caller's `verbose` flag (FR-024/FR-025).
        "--log-level", "debug",
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
    return cmd


def download(username: str, mirror: Path, session_dir: Path,
             recent: int | None = None, until_found: int | None = None,
             since: str | None = None, until: str | None = None,
             dry_run: bool = False, verbose: bool = False,
             on_line: Callable[[str], None] | None = None,
             version: str | None = None) -> CoverageProof:
    """Run icloudpd to mirror a window of the library into `mirror`.

    Returns a `CoverageProof` rather than an exit code: the caller decides
    whether a watermark may move, and needs evidence rather than a status.

      recent       -> examine only the first N items of the enumeration, which
                      iCloud orders by CAPTURE date, newest first (the All
                      Photos list type is CPLAssetAndMasterByAssetDate...).
                      This bounds the enumeration itself, not just the
                      downloads (research R1). NOTE: the ordering is what makes
                      a single skip-before-cutoff line prove everything newer
                      was examined -- if a future icloudpd changes it, §4.2 of
                      contracts/coverage-proof.md stops being sound, which is
                      the other reason TESTED_ICLOUDPD_VERSIONS is pinned.
      since        -> skip items created before this date (YYYY-MM-DD)
      until        -> skip items created after this date (YYYY-MM-DD)
      until_found  -> stop after N consecutive already-downloaded items
      dry_run      -> icloudpd's native --dry-run (touches nothing)
      verbose      -> echo icloudpd's raw per-item output to the operator
      on_line      -> optional per-line callback (progress reporting)
    """
    if not icloudpd_available():
        raise ICloudError("icloudpd not found on PATH (uv tool install icloudpd)")

    if version is None:
        version = probe_version()

    # Pre-flight: refuse before spending a long enumeration on a dead session.
    # Per-account (all accounts share this directory), and local, so a refusal
    # here costs no sign-in attempt against an account that may be locked.
    session_ok, session_why = session_status(session_dir, username)
    if not session_ok:
        return build_proof(StreamTally(), exit_code=0,
                           session_present_before=False, version=version,
                           session_detail=session_why)

    mirror.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_download_cmd(username, mirror, session_dir, recent=recent,
                             until_found=until_found, since=since, until=until,
                             dry_run=dry_run)

    tally = StreamTally()
    truncated = False
    # stdin=DEVNULL is load-bearing, not tidiness. This path captures stdout to
    # parse the coverage proof, so an interactive prompt from icloudpd is
    # INVISIBLE to the operator — and with an inherited stdin it would sit
    # waiting for a code nobody knows it wants. That happened: Apple showed a
    # sign-in, the tool sat silent forever. With DEVNULL the prompt gets EOF and
    # the run fails fast even if the detection below misses new wording.
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    try:
        # Read continuously: buffering until exit would deadlock on a full pipe
        # during a long sweep.
        assert proc.stdout is not None
        for raw in proc.stdout:
            truncated = not raw.endswith("\n")
            line = raw.rstrip("\n")
            tally.feed(line)
            if verbose:
                print(line)
            if on_line is not None:
                on_line(line)
            if tally.mfa_required:
                proc.kill()
                break
    except BaseException:
        # The reader died (a BrokenPipeError from `| head`, a failing on_line
        # callback, Ctrl-C). Stop draining and icloudpd blocks forever writing
        # into a full pipe, so kill it rather than hang the operator's terminal.
        proc.kill()
        raise
    finally:
        proc.wait()

    return build_proof(tally, exit_code=proc.returncode,
                       session_present_before=True, version=version,
                       truncated=truncated)
