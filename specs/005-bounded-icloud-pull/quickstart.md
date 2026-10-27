# Quickstart & Validation: Bounded, Honest iCloud Pulls

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

How to verify this feature does what it claims. Scenarios 1–5 are automated and
run against fixtures. Scenario 6 is the live incident repair and is an
**operator action** — it cannot be satisfied by an implementation run.

## Prerequisites

```bash
cd /Users/mattlee/CodeStuff/TheArchivist
uv sync
icloudpd --version        # expect 1.32.3; an untested version must warn + fail closed
```

No scenario below contacts a real iCloud account except Scenario 6, which is
the operator's own deliberate repair.

---

## Scenario 1 — Full suite

```bash
uv run pytest -q
```

**Expected**: all existing tests plus the new coverage-proof, advance-decision
and reconciliation suites pass. Baseline at plan time was 91 passing; 271 pass now.

`test_pull_state.py` and `test_pull_all.py` were **rewritten**, not merely
extended: their mocks returned an exit code, and two cases in `test_pull_state`
asserted the very behaviour this feature removes (a narrow `--recent N --apply`
advancing the watermark). `test_pull_window.py` gained the FR-009 overlap
regression. Shared mock builders live in `tests/integration/_pullhelp.py`.

## Scenario 2 — The incident cannot recur (SC-001)

Covers contract test #14, the exact 2026-09-26 shape.

```bash
uv run pytest tests/unit/test_advance_decision_null_ingest.py \
  tests/integration/test_pull_state.py -k "unconfirmed or incident or null" -v
```

**Expected**: a run whose download step produced no completion signal and
fetched nothing leaves `pull_state:<source>` **unchanged**, reports the source
as `FAILED` (not `OK`), and writes a journal entry with
`decision: "refuse"` and a populated `reason`.

**Counter-case in the same suite**: a genuinely quiet source — completion
signal present, `downloaded: 0` — reports `IDLE` and **does** advance. If both
pass, the tool can tell "nothing to do" from "did nothing".

## Scenario 3 — Narrow pulls never over-claim (SC-002)

```bash
uv run pytest tests/unit/test_advance_decision.py \
  tests/unit/test_advance_decision_modes.py tests/unit/test_pull_mode.py -v
```

**Expected**: the full mode × proof decision table from
[contracts/coverage-proof.md](contracts/coverage-proof.md) §6, including all
three `NARROW` triggers refusing, `EXPLICIT_SINCE` refusing when its start date
is later than the current watermark, and an advance recording run-**start**.

End-to-end form, on fixture volumes:

```bash
uv run pytest tests/integration/test_pull_narrow_then_routine.py -v
```

**Expected**: after a narrow pull, a routine refresh still requests the full
interval from the original watermark.

## Scenario 4 — The bounded scan is actually bounded (SC-007)

```bash
uv run pytest tests/integration/test_scan_bound_insufficient.py \
  tests/unit/test_bounded_args.py tests/unit/test_reached_before_cutoff.py -v
```

**Expected**: the constructed downloader argument list carries
`--recent <scan_bound>`; the run reports `examined` ≤ bound; and when the
window is not cleared, coverage is held with the `scan_bound` refusal reason.

Live timing check once deployed (SC-005):

```bash
time archivist pull all          # dry-run; downloads still occur
```

**Expected**: well under two minutes with no new media, versus a full walk of
every asset in every account today.

## Scenario 5 — Reconciliation escalates and repairs (SC-003)

```bash
uv run pytest tests/integration/test_reconciliation.py -v
```

**Expected**: a source with a stale (or absent) `reconcile_state` escalates to
an unbounded sweep and announces it before scanning; a fresh one does not; the
reconciliation watermark advances only on a clean applying sweep; a sweep files
items whose capture dates predate the coverage watermark; and one source
sweeping does not stop the others.

---

## Scenario 6 — Repair the 2026-09-26 holes (SC-004) — OPERATOR ACTION

Two sources lost coverage before this feature existed. Nothing in the
implementation repairs them retroactively; the code provides the means (FR-018)
and the operator applies it. **An implementation run must not mark SC-004
complete.**

Known holes, from the catalog at plan time:

| Source | Missing interval | Newest archived capture then |
|---|---|---|
| `peepaw-cell` | 2026-08-26 → 2026-09-19 | 2026-09-24 (post-hole only) |
| `matt-public` | 2026-08-26 → 2026-09-26 | 2026-08-26 |

Re-authenticate first. A back-dated pull under a dead session would fail, and
under the pre-feature code would have re-advanced the watermark over the same
hole:

```bash
archivist auth icloud --source peepaw-cell
archivist auth icloud --source matt-public
```

Then re-cover, one source at a time, with a week of overlap before each
source's last known-good item:

```bash
archivist pull icloud --source peepaw-cell --since 2026-08-19 --apply
archivist pull icloud --source matt-public --since 2026-08-19 --apply
```

`--since` with no upper bound and no count bound resolves to `EXPLICIT_SINCE`,
and `2026-08-19` precedes both watermarks, so the advance is honest and
permitted. Dedup makes the overlap free. The `matt-public` sweep walks ~40k
assets; allow time.

**Verify the repair**, substituting each source:

```bash
sqlite3 /Volumes/ExternalBaseUnit/TheArchivist/catalog/archivist.sqlite3 \
  "SELECT source_label, COUNT(*), MIN(substr(capture_dt,1,10)), MAX(substr(capture_dt,1,10))
     FROM assets
    WHERE source_label IN ('Peepaw Cell','Matt Public Cell')
      AND capture_dt >= '2026-08-26' AND capture_dt < '2026-09-27'
    GROUP BY 1;"
```

**Expected**: both sources return counts consistent with their normal rates
(`Peepaw Cell` ~40–70, `Matt Public Cell` ~300–450), not the 0 and 3 recorded
at plan time. A reconciliation sweep run afterwards should find nothing further
missing in those intervals.

---

## Deployment note

The first `archivist pull all --apply` after this feature ships escalates
**every** configured source to a reconciliation sweep, because no source has a
`reconcile_state` key yet ([contracts/config-schema.md](contracts/config-schema.md) §4).
That is the intended repair path, and it makes the first run long. To stage it:

```bash
archivist pull all --apply --no-reconcile      # fast; reports what is overdue
archivist pull icloud --source <one> --full --apply   # sweep one at a time
```
