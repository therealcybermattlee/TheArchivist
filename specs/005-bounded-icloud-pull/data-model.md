# Phase 1 Data Model: Bounded, Honest iCloud Pulls

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

No SQL schema migration. The catalog gains two new `meta` keys per source; the
audit history lives in a new append-only journal. Rationale for that split is
in [research.md](research.md) R5 (Constitution Principle IV: files plus
manifests authoritative, catalog derived).

---

## 1. Catalog `meta` keys

All values are strings, per the existing `meta` table contract.

| Key | Existing? | Value | Meaning |
|---|---|---|---|
| `pull_state:<source>` | yes | naive local ISO-8601, second precision | **Coverage watermark.** The archive is believed complete for this source through this instant. |
| `reconcile_state:<source>` | NEW | naive local ISO-8601, second precision | **Reconciliation watermark.** When this source last received a complete unbounded scan. |
| `coverage:<source>` | NEW | JSON object (see §3) | Latest coverage record — a fast-read mirror of the newest journal entry. Non-authoritative. |

`pull_state` keeps its existing key shape and semantics so no migration or
backfill is required; what changes is *when it is permitted to move*.

**Absent-key semantics**

- `pull_state` absent → no bootstrap on this host. Unchanged: refuse a
  stateless full pull and direct the operator to an explicit bootstrap.
- `reconcile_state` absent → treated as immediately due (FR-016). Existing
  sources have no such key, so the first routine refresh after this feature
  ships escalates every source to a sweep. **This is intended**: it is what
  repairs the 2026-09-26 holes without the operator having to know they exist.
  The run must announce it clearly, since four simultaneous sweeps is a long
  first run.

---

## 2. Entities

### CoverageWatermark

| Field | Type | Notes |
|---|---|---|
| `source` | str | config source key |
| `covered_through` | datetime (naive local) | the instant claimed |

**Invariants**

- Monotonic: never moves backwards.
- Set to the run's **start** time, never its completion time (FR-006).
- Moves only on a `Decision.advance` (see [contracts/coverage-proof.md](contracts/coverage-proof.md)).

**Transitions**

| From | Event | To |
|---|---|---|
| absent | bootstrap (`BOOTSTRAP_FULL`) with proven complete enumeration, applying | run-start |
| present | any mode whose decision is `advance` | run-start |
| present | any refusal (unproven coverage, narrow mode, ingest failure, dry-run) | unchanged |

### ReconciliationWatermark

| Field | Type | Notes |
|---|---|---|
| `source` | str | config source key |
| `reconciled_through` | datetime (naive local) | run-start of the last clean sweep |

**Invariants**

- Advances only after a `RECONCILE` or `BOOTSTRAP_FULL` run that was applying,
  whose coverage proof shows a complete unbounded enumeration, and which
  produced zero ingest failures (FR-015).
- A `ROUTINE_BOUNDED` run never advances it, however successful — a bounded
  scan is not a reconciliation.
- Independent of the coverage watermark: either may advance without the other.

**Derived predicate**

```
is_due(source, now) := reconciled_through is absent
                    or (now - reconciled_through) > reconcile_interval_days
```

### CoverageRecord

One per source per applying run. Journaled first, then mirrored to
`meta.coverage:<source>`.

| Field | Type | Notes |
|---|---|---|
| `source` | str | config source key |
| `run_id` | str | shared with the ingest manifest for that source's run |
| `mode` | PullMode | see §4 |
| `run_started` | datetime | captured before the download begins |
| `run_finished` | datetime | |
| `window_since` | date \| null | the cutoff handed to the downloader |
| `window_until` | date \| null | set only for explicit historical slices |
| `scan_bound` | int \| null | null when unbounded |
| `enumeration_complete` | bool | completion signal observed |
| `reached_before_cutoff` | bool | at least one skip-before-cutoff observed |
| `examined` | int | items the downloader considered |
| `downloaded` | int | items newly fetched |
| `already_present` | int | items the downloader found already on disk |
| `ingest_copied` | int | |
| `ingest_skipped` | int | |
| `ingest_failed` | int | |
| `decision` | "advance" \| "refuse" | |
| `reason` | str \| null | required when refusing; the text FR-008 prints |
| `claimed_through` | datetime \| null | set only when advancing; equals `run_started` |

**Invariants**

- `decision == "refuse"` ⇒ `reason` non-null and `claimed_through` null.
- `decision == "advance"` ⇒ `claimed_through == run_started`.
- Written to the journal **before** the `meta` update. An interruption between
  the two leaves the journal authoritative and the watermark stale — the safe
  direction, since a stale watermark re-covers ground while a premature one
  loses it.

### CoverageProof

Transient, not persisted on its own; its fields flow into `CoverageRecord`.
Produced by parsing the downloader's captured output. Full field list and
parsing rules in [contracts/coverage-proof.md](contracts/coverage-proof.md).

### SourceMirror

Unchanged on disk; **reclassified** in documentation and in code comments.
Transient pass-through storage under `staging/icloud/<source>`. Prunable at any
time. Carries no authoritative state and is never evidence of coverage
(FR-029, FR-030). The `icloud.py` module docstring currently describes it as a
"PERSISTENT per-source mirror" whose contents make repeat pulls incremental;
that description is wrong post-004 and is corrected as part of this work.

---

## 3. Journal format

New file per applying pull run: `logs/pull-<run_id>.jsonl`, one JSON object per
source, append-only, flushed after each write.

```jsonc
{
  "source": "peepaw-cell",
  "run_id": "20260926-140236",
  "mode": "routine_bounded",
  "run_started": "2026-09-26T14:02:04",
  "run_finished": "2026-09-26T14:02:38",
  "window_since": "2026-09-19",
  "window_until": null,
  "scan_bound": 500,
  "enumeration_complete": true,
  "reached_before_cutoff": true,
  "examined": 500,
  "downloaded": 15,
  "already_present": 0,
  "ingest_copied": 15,
  "ingest_skipped": 0,
  "ingest_failed": 0,
  "decision": "advance",
  "reason": null,
  "claimed_through": "2026-09-26T14:02:04"
}
```

`meta.coverage:<source>` holds the same object as a JSON string, latest only.

**Why the journal matters beyond audit**: had it existed on 2026-09-26, the two
bad advances would have been recorded as `downloaded: 0,
enumeration_complete: false` against a window of `2026-08-19`, and the hole
would have been a query rather than a discovery.

---

## 4. PullMode

Resolved once from CLI arguments, then carried through the run. Replaces
inferring intent from a combination of optional arguments at decision time.

| Mode | Triggered by | Downloader bounds | May advance coverage | May advance reconcile |
|---|---|---|---|---|
| `ROUTINE_BOUNDED` | no window flags, source not due | `--recent <bound>` + `--skip-created-before <cutoff>` | only with complete enumeration **and** reached-before-cutoff | never |
| `RECONCILE` | no window flags, source due | none (unbounded) | with complete enumeration | with complete enumeration + zero ingest failures |
| `BOOTSTRAP_FULL` | `--full` | none (unbounded) | with complete enumeration | with complete enumeration + zero ingest failures |
| `EXPLICIT_SINCE` | `--since D`, no `--until`, no count bound | `--skip-created-before D` | with complete enumeration **and** `D <= previous watermark` | never |
| `NARROW` | any of `--recent`, `--until-found`, `--until` | as given | **never** (FR-004) | never |
| `INGEST_ONLY` | `--no-download` | n/a | **never** | never |

Every mode additionally requires: applying run, zero ingest failures, and a
coverage proof that did not fail closed.

---

## 5. Configuration

Detail and validation rules in
[contracts/config-schema.md](contracts/config-schema.md). Summary:

| Setting | Scope | Default | Meaning |
|---|---|---|---|
| `scan_bound` | per source, global fallback | 500 | items a routine refresh examines before stopping |
| `reconcile_interval_days` | per source, global fallback | 30 | staleness after which a source escalates to a sweep |

Both are optional; absent values take the documented default, so existing
`config.yaml` files remain valid with no edits.

---

## 6. What is explicitly unchanged

- `assets` table: no column added, removed, or reinterpreted.
- `schema_version`: stays at 3. New `meta` keys need no migration; absent keys
  have defined semantics (§1).
- Ingest, grouping, dating, hashing, location, dedupe, quarantine, purge, and
  prune data models: untouched.
- The 7-day window overlap subtracted when computing a routine cutoff (FR-009).
