# Implementation Plan: Run The Archivist on a Linux Host (Proxmox)

**Branch**: `004-linux-proxmox-host` | **Date**: 2026-07-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-linux-proxmox-host/spec.md`

## Summary

Make The Archivist run with full parity on a Debian VM on the family
Proxmox host (LXC variant validated second), as the new primary operator
host. The work splits into three strands: **(1) portability fixes** —
replace `sips` with cross-platform thumbnail backends (pillow-heif for
HEIC, exiftool embedded-preview extraction for RAW), make the iCloud
keyring work headless, harden dedup/collision logic for case-sensitive
filesystems, and fail fast on host-invalid config paths; **(2)
working-storage discipline** — windowed incremental pulls (per-source
last-pull state instead of persistent full mirrors) plus a new guarded
`prune-staging` command that removes only verified-archived staged media,
keeping the working volume within its ~50 GB budget; **(3) deployment &
validation** — a `doctor` environment check, a migration guide covering VM
and LXC provisioning, state migration (catalog + manifests only), and the
host-agnostic validation checklist that must pass identically on macOS,
the VM, and the LXC.

## Technical Context

**Language/Version**: Python 3.12+ — via `uv`-managed CPython on all hosts
(no dependence on the distro's system Python; Debian stable ships older)

**Primary Dependencies**: existing `typer`, `pyyaml`, `pillow`, `tzdata` +
NEW `pillow-heif` (cross-platform HEIC read/write — replaces `sips`);
external executables `exiftool` (metadata + RAW embedded-preview
extraction), `ffmpeg`/`ffprobe`, `icloudpd`. Linux keyring backend for
icloudpd sessions: `gnome-keyring` (headless via D-Bus session), with
hard-refusal if no secure backend is available (FR-010)

**Storage**: unchanged layouts — archive share mounted from TrueNAS (NFS
for the VM; host-managed bind mount for LXC); working volume ≈50 GB
guest-local ext4 virtual disk (per clarification: media transits only);
catalog gains per-source pull-state keys in the existing `meta` table

**Testing**: same `pytest` suite, now required green on Linux (FR-002);
new tests: case-sensitivity fixtures (FR-009), prune safety (FR-016),
windowed-pull state, doctor checks; fixture builder switches HEIC creation
from `sips` to `pillow-heif` so tests are host-agnostic

**Target Platform**: Debian stable VM on Proxmox (reference), LXC variant
second, macOS retained for development/fallback — one applying host at a
time

**Project Type**: Single-project CLI (same `src/archivist` package;
portability work is in-place, no fork)

**Performance Goals**: unchanged scan/ingest targets; steady-state working
storage < 50 GB over a month of pull-and-prune (SC-008); guest-local
staging writes at local-disk speed, archive writes over wired LAN to the
NAS

**Constraints**: every baseline safety invariant unchanged (FR-005/006);
prune may delete ONLY inside the tool's own working area and ONLY items
whose verified archived copy is confirmed (FR-016 — this is the feature's
single new deletion path and gets the heaviest test scrutiny); no
plaintext credential fallback ever (FR-010); filing decisions independent
of host timezone (FR-008)

**Scale/Scope**: same archive (≈5,300 items / ≈3 TB); three iCloud
accounts pulled in small recent windows; one-time full-library bootstrap
completes on the Mac before cutover and does not recur

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` remains an unratified template; the
baseline safety invariants govern:

| Gate | Status |
|------|--------|
| No code path writes to a source or archived file | PASS — portability work touches no filing logic semantics |
| Writes confined to archive + working volumes | PASS — unchanged |
| Only deletions: inside `_Quarantine` + own working scratch, on explicit request | PASS with scrutiny — NEW `prune-staging` deletes inside the tool's own staging area only, dry-run default, verified-archived-only, journaled (FR-016); exactly the "own scratch, when asked" carve-out PLAN.md always allowed |
| Volume sentinel guard before any state-changing command | PASS — guard is already POSIX-portable; Linux tests prove the unmounted-share failure mode |
| Dry-run default; `--apply` gates every mutation | PASS — prune follows the same contract |
| No credentials outside secure storage | PASS — hard refusal when no secure backend exists (FR-010), never plaintext |

No violations; Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: PASS — the design adds one
deletion-capable command (`prune-staging`) that is triple-guarded
(own-area path containment, catalog-verified-archived check, plan/apply +
journal), one read-only `doctor` command, and dependency swaps that do not
touch safety-relevant code paths.

## Project Structure

### Documentation (this feature)

```text
specs/004-linux-proxmox-host/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── cli-interface.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/archivist/
├── config.py       # MODIFY: fail-fast host-path validation (FR-007)
├── mapexport.py    # MODIFY: thumbnail backends — Pillow native,
│                   #   pillow-heif (HEIC), exiftool embedded-preview (RAW),
│                   #   ffmpeg (video); `sips` dependency removed
├── metadata.py     # MODIFY: add embedded-preview extraction helper
├── icloud.py       # MODIFY: windowed pulls — per-source last-pull state,
│                   #   default `--since` window; keyring-backend probe
├── staging.py      # NEW: prune-staging engine — plan/apply, catalog-
│                   #   verified-archived containment, journal (FR-015/016)
├── ingest.py       # MODIFY: case-insensitive collision hardening +
│                   #   same-hash-at-destination skip (PLAN.md §E parity)
├── catalog.py      # MODIFY: meta-table helpers for per-source pull state
├── hashing.py      # (no change — already portable)
├── guard.py        # (no change — POSIX-portable; Linux tests prove it)
└── cli.py          # MODIFY: `doctor` command (env/tool/keyring/config
                    #   checks), `prune-staging` command, no sips references

tests/
├── fixtures/build_fixtures.py  # MODIFY: HEIC via pillow-heif (drop sips)
├── unit/           # NEW: case-sensitivity collision/dedup, pull-window
│                   #   math, prune plan rules, doctor checks
└── integration/    # NEW: prune end-to-end (never removes unverified),
│                   #   windowed pull state advance, Linux-parity suite run

docs/
└── linux-host.md   # NEW: migration guide — VM + LXC provisioning, mounts,
                    #   keyring setup, state migration, validation checklist,
                    #   one-applying-host-at-a-time rule
```

**Structure Decision**: All portability work happens in-place in the
existing modules — no platform abstraction layer; the only platform-aware
code is thumbnail backend selection and the keyring probe, both small
enough to live where they're used. `staging.py` is the one new module
(mirrors `dedupe.py`'s plan/apply shape for a deletion-capable feature).
The migration guide lives in `docs/` (new directory), not in specs.

## Gap Analysis (current code vs. this feature)

| Spec item | Current state | Work |
|-----------|--------------|------|
| FR-001/002 parity + suite green on Linux | Untested on Linux; `sips` hard dependency in mapexport + test fixtures | Backend swap, then run suite on the VM |
| FR-003 HEIC/RAW thumbnails sans macOS tools | `sips` for both | pillow-heif (HEIC) + exiftool preview (RAW) |
| FR-004 terminal-only flows | Already terminal-based | Verify over SSH (auth 2FA especially) |
| FR-007 config path fail-fast | Paths checked only by guard at run time | Add explicit validation with actionable messages |
| FR-008 host-TZ independence | dates.py uses configured TZ; untested against host TZ variance | Test with `TZ=` variations |
| FR-009 case-sensitivity | `_collision_free` uses `dst.exists()`; grouping lowercases stems | Audit + fixture tests on case-sensitive fs |
| FR-010/011 headless keyring, per-host sessions | Works on macOS Keychain only | gnome-keyring setup + probe + refusal path |
| FR-015 windowed pulls | Persistent-mirror model (`--until-found`/full) | Per-source last-pull state, default `--since` |
| FR-016 prune-staging | Does not exist | New `staging.py` + CLI command |
| FR-012/013/014 VM+LXC, migration guide | Nothing | `docs/linux-host.md` + validation checklist |
