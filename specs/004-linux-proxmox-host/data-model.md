# Data Model: Run The Archivist on a Linux Host (Proxmox)

**Feature**: 004-linux-proxmox-host | **Date**: 2026-07-31

This feature adds no new tables. It extends the catalog's existing `meta`
key-value table, formalizes the staging area's lifecycle, and defines the
prune journal. Baseline entities: [001 data-model.md](../001-archivist-baseline/data-model.md);
location columns: [002 data-model.md](../002-media-geolocation/data-model.md).

## Pull State (catalog `meta` table, new keys)

| Key | Value | Notes |
|-----|-------|-------|
| `pull_state:<source-key>` | ISO date-time of the last **successfully completed** pull for that source | Written only after the pull + ingest finish without fatal error |

**Rules** (FR-015, research D5):
- Routine pull window = `last_pull − 7 days` (overlap absorbs clock skew /
  late cloud arrivals; catalog dedup makes overlap harmless — re-pulled
  archived content files zero items).
- No state present (fresh host, rebuilt catalog): the pull requires an
  explicit `--recent N` / `--since DATE` / `--full` — never silently pulls
  the whole library.
- State migrates with the catalog (copy path) because it lives in the
  catalog; a rebuilt catalog legitimately has no state.

## Staged Media Item (filesystem + derived status, no table)

Any file under the tool's own staging areas:
`<work_base>/staging/**` (including `staging/icloud/<source>/**`) and
`<work_base>/drops/<source>/**` is a *staged media item*. Its prune status
is **derived at plan time**, never stored:

| Status | Definition | Prunable? |
|--------|-----------|-----------|
| `verified-archived` | full SHA-256 matches a catalog row with non-null `archive_path` AND that archive file exists on the mounted archive right now | YES |
| `unverified` | no catalog match by content hash | NO — may be the only copy |
| `archived-missing` | catalog match but the archived file is absent on disk | NO — archive integrity question; surfaced loudly in the plan |
| `outside-staging` | path escapes the staging roots after resolution (symlink, mount trick) | NO — refused and reported |

**State transitions**:

```
downloaded/dropped ──> unverified ──(ingest copies+verifies+catalogs)──> verified-archived
verified-archived ──(prune-staging --apply)──> deleted from staging (journaled)
verified-archived ──(archive file later missing at plan time)──> archived-missing (prune refuses)
```

**Invariants** (FR-016):
- Deletion only inside resolved staging roots; symlinks never followed.
- Every deletion journaled before the unlink.
- Drops inboxes are included in pruning scope but with the same
  verified-archived-only rule (a drop that was never ingested is
  untouchable).

## Prune Journal (`logs/prune-<timestamp>.jsonl`)

One line per action, written **before** the unlink:
`{run_id, staged_path, content_hash, archive_path, size, action: "delete", result}`
plus plan-level entries for refusals `{staged_path, status, reason}` so the
journal is a complete account of what was and wasn't touched, and why.

## Doctor Report (in-memory, rendered by `archivist doctor`)

| Check | Content |
|-------|---------|
| Config | resolved path, `archive_root`/`work_root` existence on this host (FR-007) |
| Volumes | guard status incl. sentinels (read-only check) |
| Executables | exiftool / ffmpeg / ffprobe / icloudpd presence + versions |
| Python/runtime | interpreter version, pillow-heif import OK |
| Keyring | functional secure backend probe (set/get/delete a throwaway secret); named backend; hard-fail advice when absent (FR-010) |
| Timezone | configured `default_timezone` resolves via tzdata; host TZ noted as irrelevant to filing (FR-008) |
| Working storage | bytes used vs. the 50 GB budget; largest staging subtrees |

Exit code: 0 all-green, non-zero if any required check fails.

## Host Profile (documentation entity — `docs/linux-host.md`)

Not code: the migration guide's per-hosting-type provisioning matrix
(VM: NFS mount + guest-local 50 GB ext4 work disk; LXC: host-side NFS +
bind mounts, privileged and unprivileged/idmap variants), the state
migration procedure (catalog + logs only; mirrors do not migrate; sessions
re-auth per host), and the three-host validation checklist (macOS / VM /
LXC) satisfying SC-003.

## Modified behavior (existing entities, no schema change)

- **Collision policy** (`_collision_free`): destination-name collision
  detection becomes case-insensitive against existing siblings and planned
  destinations (FR-009) — case-twin names get hash suffixes on every
  platform, keeping layouts portable across SMB/NFS semantics.
- **Thumbnail generation** (`mapexport`): backend table becomes
  Pillow-native / pillow-heif (HEIC-HEIF) / exiftool embedded preview
  (RAW) / ffmpeg (video); behavior contract (per-item graceful failure,
  ~800 px JPEG output) unchanged.
- **Cloud session**: unchanged shape, explicitly per-host (FR-011);
  keyring backend differs by platform (Keychain / Secret Service).
