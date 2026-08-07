# CLI Contract: Linux Host & Working-Storage Discipline

**Feature**: 004-linux-proxmox-host | **Date**: 2026-07-31

Extends the baseline contract ([001](../../001-archivist-baseline/contracts/cli-interface.md))
and geolocation contract ([002](../../002-media-geolocation/contracts/cli-interface.md)).
Global guard/dry-run/exit-code behavior unchanged and now explicitly
identical on macOS and Linux (FR-001).

## New commands

### `archivist doctor`

Read-only environment and provisioning health check (research D8).

- **Reports**: config path validity for THIS host, volume guard status,
  required executables + versions, HEIC support import, keyring secure
  backend probe, timezone resolution, working-storage usage vs. 50 GB
  budget.
- **Exit**: `0` all required checks green; non-zero otherwise, each
  failure with an actionable remedy line. A check is *required* only when
  the configuration demands it: `icloudpd` and the keyring probe are
  required only if at least one `icloud` source is configured; otherwise
  they report as informational. Config validity, volumes, exiftool,
  ffmpeg/ffprobe, HEIC support, and timezone resolution are always
  required.
- **Guard**: none required (read-only, must work on a half-provisioned
  host — that's its job).

### `archivist prune-staging [--source KEY] [--apply]`

Guarded cleanup of the tool's own staged media (FR-015/FR-016).

- **Plan (default)**: lists every staged file with derived status
  (`verified-archived` / `unverified` / `archived-missing` /
  `outside-staging`), reclaimable bytes, and refusal reasons. Nothing is
  touched.
- **Apply**: deletes ONLY `verified-archived` items (full-hash match to a
  cataloged row whose archived file exists on the mounted archive at apply
  time), inside resolved staging roots only, symlinks refused, each unlink
  journaled first to `logs/prune-<ts>.jsonl`.
- **Guard**: volume guard REQUIRED (verification needs the live archive).
- **Report**: deleted count + bytes reclaimed, refused counts by status;
  `archived-missing` items are highlighted as archive-integrity warnings.
- **Exit**: `0` on success (including "nothing prunable"); non-zero on
  guard failure or mid-run volume loss (halt; journal accounts for
  completed deletions).

## Modified commands

### `archivist pull icloud --source KEY [...]` (FR-015)

- Routine invocation (no window flags): uses the source's stored pull
  state — downloads items created since `last_pull − 7 days`. On success
  (download + ingest complete), advances `pull_state:<source>`.
- No stored state (fresh/rebuilt catalog): refuses to run stateless
  without an explicit `--recent N`, `--since DATE`, or `--full`
  (bootstrap acknowledgement) — never silently mirrors a whole library.
- Existing flags unchanged; `--full` documents itself as a
  bootstrap-scale operation.
- Re-pulling overlap or already-archived content always files zero new
  items (catalog dedup; SC/FR-015).

### `archivist auth icloud --source KEY`

- Unchanged interface; on hosts without a functional secure keyring
  backend it MUST refuse with setup instructions (FR-010) — never store
  or prompt toward plaintext.

### `archivist export-map`

- Same interface; thumbnail generation now uses pillow-heif (HEIC/HEIF)
  and exiftool embedded-preview extraction (RAW) — no `sips` on any
  platform; per-item failure behavior unchanged.

### `archivist status`

- Adds working-storage usage line (used / 50 GB budget) so budget
  pressure is visible in the daily view; deep diagnostics stay in
  `doctor`.

### All state-changing commands

- Config loading fails fast with an actionable message when configured
  roots do not exist on this host (FR-007) — e.g., a Mac `/Volumes/…`
  path on the Linux guest names the mismatch explicitly.

## Platform contract (FR-001/FR-004)

Every command above, and every pre-existing command, behaves identically
on macOS and Debian-family Linux: same flags, same refusals, same exit
codes, terminal-only interaction throughout (SSH-safe). Platform-specific
provisioning (mounts, keyring daemon) lives in `docs/linux-host.md`, never
in command semantics.
