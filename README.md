# The Archivist

Personal media-archival CLI for the Lee Family library. Safely pulls photos/videos
from iCloud, Google Takeout, physical devices, and drop folders, and sorts them by
capture date into the existing `YEAR / "MMDDYYYY - Event" / Device` structure on a
TrueNAS archive.

See **[PLAN.md](./PLAN.md)** for the full design and the data-flow safety invariant.

## Safety invariant
Source data is read-only, always:
`source --(copy)--> /Volumes/ExternalBaseUnit (stage/decide) --(copy+verify)--> /Volumes/VideoStorage (archive)`.
Dry-run by default; `--apply` gates every write; archive copies are hash-verified
before the catalog records them.

## Setup
```bash
uv sync
cp config.example.yaml config.yaml   # adjust paths/sources
uv run archivist status              # check volumes + catalog
uv run archivist init-volumes        # one-time: write sentinels, init catalog
```

## Capture locations & the map export
The catalog records WHERE media was captured (when the file carries embedded
location metadata) alongside when. Nothing is ever inferred or sent to any
external service — coordinates live only in the local catalog and in exports
you explicitly create (a future map viewer may use online map services for
display; the database itself stays local).

```bash
uv run archivist scan-locations        # backfill locations for already-archived media
                                       # (reads files in place; incremental; resumable)
uv run archivist status                # includes location coverage by year/source
uv run archivist export-map            # Google Earth .kmz with clickable photo pins
uv run archivist export-map --year 2024 --source "Peepaw Cell"
```

Exports land in `<work_root>/TheArchivist/exports/`. Open the `.kmz` in Google
Earth desktop and click a pin to see the photo (HEIC/video get generated JPEG
thumbnails). New ingests capture location automatically — no extra step.

## Running on Linux (Proxmox guest)

The tool runs identically on macOS and Debian-family Linux — see
**[docs/linux-host.md](./docs/linux-host.md)** for provisioning (VM or LXC),
headless keyring setup, state migration, and the per-host validation
checklist. Highlights:

```bash
uv run archivist doctor           # environment health check for THIS host
uv run archivist pull all --apply # routine refresh: every iCloud source, each
                                  # windowed since its own last success (−7d overlap)
uv run archivist pull icloud --source X --apply    # or one source at a time
uv run archivist prune-staging    # plan: reclaim staged files whose VERIFIED
uv run archivist prune-staging --apply   # archived copy exists (journaled)
```

`pull all` keeps going when one account fails (expired session, ingest error);
that source simply doesn't advance its state, so the next run re-covers the
same window. The closing summary names anything to re-run.

Working storage is a small transient pass-through (~50 GB budget — shown in
`status`); media's permanent home is always the TrueNAS archive. Only one
host runs `--apply` operations at a time.

## Tests
```bash
uv run pytest    # unit + integration; uses tmp-dir fake volumes, never /Volumes/*
```
Integration fixtures generate tiny real media with genuine GPS/date metadata
(requires `exiftool`, `ffmpeg`, and macOS `sips` on PATH).

## Status
Delivered: `status`, `init-volumes`, `scan-archive`, `ingest`, `ingest-drops`,
`cleanup`, `purge`, `auth icloud` / `pull icloud` / `pull all`,
`scan-locations`, `export-map`, `prune-staging`, `doctor`. See `specs/` for
feature specs (001 baseline, 002 geolocation, 003 Immich viewer, 004 Linux host).
