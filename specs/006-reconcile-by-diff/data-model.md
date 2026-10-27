# Phase 1 Data Model: Reconciliation by Enumeration Diff

No new database tables. One new `meta` key, two new journal record shapes, and
five in-memory types.

## 1. In-memory types (`src/archivist/audit.py`, except where noted)

### `Listing` (in `icloud.py`, beside `CoverageProof`)

What one enumeration produced, and whether it may be trusted.

| Field | Type | Meaning |
|---|---|---|
| `paths` | `frozenset[str]` | Target paths, **relative to the mirror root**, deduplicated (research R4) |
| `listed_lines` | `int` | Raw line count before dedup — reported, never compared |
| `complete` | `bool` | Exit 0, no failure signal, final line well-formed (R3) |
| `exit_code` | `int` | Process exit status |
| `notes` | `tuple[str, ...]` | Every reason completeness was not established |

**Invariant**: `complete` false ⇒ `paths` may not be used for any verdict.
Mirrors `CoverageProof.parser_confident`; the same fail-closed discipline.

### `GapReport`

The comparison's outcome. Deliberately an upper bound.

| Field | Type | Meaning |
|---|---|---|
| `source` | `str` | Source key |
| `listed` | `int` | Unique paths in the listing |
| `archived` | `int` | Catalog rows matching the source's mirror prefix |
| `missing` | `tuple[str, ...]` | Relative paths listed but not recorded, sorted |
| `by_month` | `dict[str, int]` | `"YYYY-MM"` → count, derived from the path, **after** comparison (R5) |
| `undated` | `int` | Missing paths whose month could not be read from the path |

`missing_count` = `len(missing)`. `by_month` plus `undated` always sums to it —
an item whose month is unreadable is reported, never dropped (edge case).

### `Verdict`

| Variant | Carries | May advance reconciliation |
|---|---|---|
| `Reconciled` | `listed`, `checked_at` | **Yes** |
| `Incomplete` | `GapReport` | No |
| `Unverified` | `reason: str` | No |

Three states, not a bool: "nothing missing", "things missing", and "could not
tell" are operationally different, and collapsing the third into either of the
others is how 005's loss happened.

### `RepairPlan`

| Field | Type | Meaning |
|---|---|---|
| `ranges` | `tuple[tuple[date, date], ...]` | Inclusive month spans to fetch |
| `expected_items` | `int` | Items the ranges are expected to deliver |
| `expected_missing` | `int` | Of those, the ones actually missing |
| `estimated_bytes` | `int \| None` | `None` when no median size exists (R8) |
| `too_scattered` | `bool` | Distinct months exceed the scatter cutoff |

**Invariant**: `estimated_bytes is None` is treated as *over budget*, never as
*within* (FR-030).

### `BudgetDecision`

`Repair(plan)` or `Report(plan, reason)`. Produced by comparing
`estimated_bytes` against `repair_budget_bytes`; `too_scattered` or a `None`
estimate forces `Report`.

## 2. Persistent state

### `meta` keys

| Key | Existing | Meaning |
|---|---|---|
| `pull_state:<source>` | 005 | Coverage watermark — **untouched by this feature** |
| `reconcile_state:<source>` | 005 | Reconciliation watermark — now advanceable by a clean audit |
| `audit_state:<source>` | **new** | ISO timestamp of the last *completed* audit, drives the 7-day interval |

`audit_state` is separate from `reconcile_state` because they answer different
questions: when did we last *look*, versus when did we last *prove it clean*. An
audit that finds a gap updates `audit_state` (we looked) but not
`reconcile_state` (it isn't clean). Without the split, a source with a persistent
gap would be re-audited on every run forever.

### Journal records (`logs/pull-<run_id>.jsonl`)

Appended by the existing `append_record`, fsynced before any catalog write.

**Audit record** — `kind: "audit"`:

```json
{"kind": "audit", "source": "matt-public", "run_id": "20261027-120000",
 "started": "...", "finished": "...", "listed": 39932, "listed_lines": 39945,
 "archived": 39932, "missing": 0, "months_affected": 0, "undated": 0,
 "listing_complete": true, "verdict": "reconciled",
 "reason": null, "reconcile_advanced_to": "2026-10-27T12:00:00"}
```

**Repair record** — `kind: "audit_repair"`: adds `ranges`, `estimated_bytes`,
`budget_bytes`, `decision` (`"repair"` / `"report"`), and the post-repair
re-audit's `missing`.

A record is written for **every** audit, including `Unverified` ones. The
journal is the evidence that a claim was examined, so a refusal is as much a
record as an advance.

## 3. Configuration

| Setting | Default | Scope | Validation |
|---|---|---|---|
| `audit_interval_days` | `7` | top level + per source | positive int |
| `repair_budget_gb` | `5` | top level + per source | positive number |
| `auto_repair` | `true` | top level | bool |

`repair_budget_gb` is converted once to `repair_budget_bytes`. Per-source
overrides follow the existing `scan_bound_for` / `reconcile_interval_for`
pattern.

## 4. State transitions

```
                 credentials unusable ──────────────► Unverified (no network touched)
                           │
   audit due ──► enumerate ─┼─ listing incomplete ───► Unverified
                           │
                           ├─ unfiled files in mirror ► Unverified  (R7, FR-008)
                           │
                           └─ compare ─┬─ missing == 0 ─► Reconciled
                                       │                   └─ advance reconcile_state
                                       └─ missing > 0 ──► Incomplete
                                                           ├─ within budget ─► repair ─► re-audit
                                                           └─ over budget ───► report only
```

`audit_state` advances on every arrow that reaches `compare`. `reconcile_state`
advances only on `Reconciled`, and only under `--apply`.

## 5. Relationship to 005

| 005 concept | How 006 uses it |
|---|---|
| `CoverageProof` | Untouched. A repair fetch still produces one. |
| `decide_advance` | Untouched. Still the sole authority on *coverage* advances. |
| `may_advance_reconcile` | **Extended**: a clean audit becomes a second legitimate route to a reconciliation advance, alongside an unbounded sweep. |
| `PullMode` | Gains no member. An audit is not a pull. A repair carries both a `since` and an `until`, which 005 already classifies as `NARROW` — and `NARROW` cannot advance a coverage watermark, which is exactly right: fetching September proves nothing about the window as a whole. The reconciliation advance comes from the re-audit instead. |
| `append_record` | Reused verbatim, with `kind` distinguishing record shapes. |
| `session_status` | Reused verbatim as the enumeration precondition. |
