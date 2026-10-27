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

### Coverage: what the tool is willing to claim

A source's **coverage watermark** is the tool's assertion that the archive is
complete for it through an instant, and it moves only on proven coverage — a
completion signal from the downloader itself, not a process exit code. A run
that couldn't do its job holds the watermark and says why, so the interval it
missed stays owed. Every advance is journaled to `logs/pull-<run>.jsonl` with
the window it claimed and the counts behind it.

Read the summary for the difference between **IDLE** (proven nothing new) and
**FAILED** (couldn't work). **PARTIAL** means the run did real work but declined
to over-claim — usually a `scan_bound` too small for that source; raise it and
re-run. `--recent` / `--until-found` / `--until` never advance coverage: they
fetch a slice, which says nothing about the interval since the watermark.

Routine refreshes examine a bounded slice of each source, so their cost tracks
what changed rather than what exists. Because a recency-bounded scan can't see
media added recently but *captured* long ago, each source needs a full sweep on
a cadence (`reconcile_interval_days`, default 30).

A sweep re-downloads the whole library, because the mirror is transient. With
`auto_reconcile: true` the tool schedules sweeps itself. With
`auto_reconcile: false` — the setting on this archive, because one pass across
all four accounts is ~246 GB against a ~50 GB working budget — you schedule
them, one source at a time:

```bash
uv run archivist pull icloud --source X --full --apply
uv run archivist prune-staging --apply
```

Either way the run **reports** what's overdue and what to run. Turning
escalation off suppresses the sweep, never the warning.

**First run after upgrading to 005**: no source has a reconciliation watermark
yet, so every configured account is due and the first `pull all --apply` sweeps
them all. That's the intended repair pass and it takes a while. To stage it:

```bash
uv run archivist pull all --apply --no-reconcile           # fast; reports overdue
uv run archivist pull icloud --source X --full --apply     # sweep one at a time
```

To re-cover a gap you already know about, reach behind the watermark:

```bash
uv run archivist pull icloud --source X --since YYYY-MM-DD --apply
```

That's permitted only when the date is at or before the current watermark; a
later one would silently skip the span between, and is refused with it named.

Working storage is a small transient pass-through (~50 GB budget — shown in
`status`); media's permanent home is always the TrueNAS archive. Only one
host runs `--apply` operations at a time.

## Tests
```bash
uv run pytest    # unit + integration; uses tmp-dir fake volumes, never /Volumes/*
```
Integration fixtures generate tiny real media with genuine GPS/date metadata
(requires `exiftool`, `ffmpeg`, and macOS `sips` on PATH). Pull tests mock the
downloader and parse recorded output fixtures — no test contacts a real iCloud
account.

### Duplicate checks and archive integrity

Ingest proves a staged file is already archived by hashing it fresh and
comparing against the catalog's recorded hash, after confirming the archived
file still exists and still has its recorded size. It re-reads the archived
bytes for a 1% sample, and whenever a size has drifted. `--verify-archive`
re-reads every candidate:

```bash
uv run archivist ingest <dir> --source X --verify-archive
uv run archivist pull icloud --source X --full --apply --verify-archive
```

Re-reading everything used to be the only mode, at ~25 files/min over SMB — a
33k-file sweep took ~22 hours, so in practice it stopped being run at all. If a
re-read ever disagrees with the catalog, the file is **filed, never skipped**,
and the run prints a loud archive-integrity warning: do not prune staging until
`scan-archive` has assessed it. See constitution Principle III (amended
2026-09-28) for what this trades away.

## Run journals
Every applying run appends to an append-only JSONL manifest under
`<work>/TheArchivist/logs/`, written *before* the catalog is touched so an
interruption leaves a complete record:

| File | Written by |
|------|-----------|
| `ingest-<run>.jsonl`  | every archive copy |
| `cleanup-<run>.jsonl` | every quarantine move |
| `prune-<run>.jsonl`   | every staged-file delete |
| `pull-<run>.jsonl`    | every coverage decision, advanced or refused |

## Status
Delivered: `status`, `init-volumes`, `scan-archive`, `ingest`, `ingest-drops`,
`cleanup`, `purge`, `auth icloud` / `pull icloud` / `pull all`,
`scan-locations`, `export-map`, `prune-staging`, `doctor`. See `specs/` for
feature specs (001 baseline, 002 geolocation, 003 Immich viewer, 004 Linux
host, 005 bounded/honest iCloud pulls).
