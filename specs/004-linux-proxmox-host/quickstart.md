# Quickstart: Validating The Archivist on the Linux Host

**Feature**: 004-linux-proxmox-host | **Date**: 2026-07-31

The same checklist runs on three hosts — macOS (regression), the Debian VM
(reference), then the LXC (portability) — per research D12 / SC-003.
Command semantics: [contracts/cli-interface.md](contracts/cli-interface.md);
prune statuses and pull state: [data-model.md](data-model.md);
provisioning detail: `docs/linux-host.md` (built by this feature).

## Prerequisites (VM reference deployment)

- Debian stable VM on Proxmox: small system disk + 50 GB ext4 working
  disk mounted (e.g., `/srv/archivist-work`), TrueNAS archive share NFS-
  mounted (e.g., `/mnt/archive`), clock on UTC + NTP.
- `uv`, `exiftool`, `ffmpeg`, `icloudpd` installed; `gnome-keyring`
  provisioned per the migration guide.
- `config.yaml` on the guest pointing at the Linux mount paths; sentinels
  present (`archivist init-volumes` once against the mounted volumes).

```bash
uv sync
uv run archivist doctor    # Scenario 0 — must be fully green before anything else
```

## Scenario 0 — Doctor (FR-007/010, research D8)

- **Expected**: all checks green on a correctly provisioned guest. Then
  break things deliberately: point config at a Mac-style `/Volumes/...`
  path (fail-fast with actionable message); stop the keyring daemon
  (keyring check fails with setup remedy; `auth icloud` refuses).

## Scenario 1 — Suite green on Linux (FR-002, SC-001)

```bash
uv run pytest
```

- **Expected**: full suite passes — including the HEIC fixtures now built
  via pillow-heif — with zero undeclared platform skips.

## Scenario 2 — Guard rails on NFS (FR-005, SC-002)

Unmount the archive NFS share (or remove its sentinel); run each
state-changing command (`ingest`, `cleanup`, `purge`, `scan-locations`,
`export-map`, `prune-staging`, `pull icloud`).

- **Expected**: every one refuses, names the failed check, exits non-zero,
  touches nothing — matching the Mac check-for-check. Remount; `status`
  healthy.

## Scenario 3 — Filing parity + timezone independence (FR-008/009, SC-007)

Ingest the standard GPS/date fixture set on the Linux host; compare
planned target paths byte-for-byte with the Mac's plan for the same
fixtures. Repeat with `TZ=UTC` and `TZ=Asia/Tokyo` exported.

- **Expected**: identical target paths in all runs. Case-sensitivity
  check: a fixture pair differing only by filename case (different
  content) plans two suffixed destinations, not case-twins; a
  byte-identical case-twin is skipped as a duplicate.

## Scenario 4 — Headless iCloud auth + windowed pull (FR-004/010/011/015, SC-004)

**PRECONDITION**: populate the VM catalog first — copy `catalog/` + `logs/`
from the Mac (Scenario 7's copy path) or run `scan-archive` +
`scan-locations` on the VM. A live `--apply` pull against an empty catalog
cannot recognize already-archived content and would re-file duplicates into
the real archive.

Over SSH (no desktop):

```bash
uv run archivist auth icloud --source matt-personal     # password + 2FA in terminal
uv run archivist pull icloud --source matt-personal --recent 25 --apply   # establishes state
uv run archivist pull icloud --source matt-personal --apply               # windowed: since last_pull − 7d
uv run archivist pull icloud --source matt-personal --apply               # immediate re-run
```

- **Expected**: auth works in the plain terminal, session persists
  (keyring + cookie); the stateless first pull REFUSES without an explicit
  window (then runs with `--recent 25`); subsequent bare pulls use the
  stored window and advance it on success; immediate re-run downloads
  little and files zero items; `grep -ri password` over config/logs/
  manifests finds nothing.

## Scenario 5 — Prune staging, safely (FR-016, SC-008)

```bash
uv run archivist prune-staging              # plan
uv run archivist prune-staging --apply
uv run archivist prune-staging              # plan again: nothing prunable
```

- **Expected**: plan classifies staged files; apply deletes ONLY
  verified-archived items and journals each deletion; bytes reclaimed
  reported. Safety probes: put a never-ingested file in a drops inbox
  (refused as `unverified`); temporarily rename an archived counterpart
  (its staged copy refused as `archived-missing` with a loud warning);
  symlink from staging to elsewhere (refused `outside-staging`).
  `status` shows working-storage usage back under budget.

## Scenario 6 — Map export parity (FR-003, SC-006)

```bash
uv run archivist export-map --year 2026
```

- **Expected**: KMZ generated with HEIC thumbnails (pillow-heif) and RAW
  thumbnails (exiftool embedded preview) present; opens in Google Earth
  desktop with clickable photo pins, equivalent to a Mac-produced export
  of the same subset.

## Scenario 7 — State migration (US4, SC-005)

Copy path: stop Mac operations, copy `catalog/` + `logs/` to the guest's
working volume, run `status`.
- **Expected**: totals, location coverage, and review-queue depth match
  the Mac's numbers; pull state came along (bare `pull icloud` uses it).

Rebuild path (alternative): fresh `scan-archive` + `scan-locations`.
- **Expected**: catalog reconciles with archive contents; bare pulls
  refuse until given an explicit window (state legitimately absent).

## Scenario 8 — LXC variant (FR-012/013, SC-003)

Repeat Scenarios 0–6 in the LXC deployment (host-side NFS + bind mounts
per the migration guide).
- **Expected**: identical results with the identical `config.yaml`
  (paths matching the container's mount points); any host-side permission
  mapping error surfaces as a guard refusal, not partial operation.

## Month-after check (SC-008)

After ~a month of routine pull-and-prune operation on the guest:
working-storage usage < 50 GB; prune journals show zero deletions of
anything but verified-archived items.
