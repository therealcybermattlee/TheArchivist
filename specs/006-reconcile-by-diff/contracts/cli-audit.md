# Contract: CLI Surface

## 1. `archivist audit`

```
archivist audit --source <key> [--apply] [--repair] [--show N] [--config PATH]
archivist audit --all [--apply] [--repair]
```

| Flag | Meaning |
|---|---|
| `--source` | One iCloud source. Mutually exclusive with `--all`. |
| `--all` | Every iCloud source, continuing past a failure. |
| `--apply` | Permit state writes (`audit_state`, and `reconcile_state` on a clean audit). Default is report-only (Principle II). |
| `--repair` | On a gap, fetch the affected ranges if within budget. Requires `--apply`. |
| `--force` | Audit even if inside the interval. |
| `--show` | Sample missing paths to print. Default 12. |

**Output, clean source:**

```
=== matt-public ===
  listing (matt-public@example.com) — no media transferred
  listed 39,932 items (39,945 lines)        [04:12]
  archived 39,932 — nothing missing
  RECONCILED -> 2026-10-27T12:04:19
```

**Output, gap found:**

```
=== peepaw-cell ===
  listed 12,073 items (12,081 lines)        [01:48]
  archived 11,402 — 671 missing (upper bound)
     2026-09   412
     2026-10   259
  sample: 2026/09/IMG_1822.HEIC, 2026/09/IMG_1822.MOV, ...
  estimated 2.5 GB across 2 months — within the 5.0 GB budget
  repair:  archivist audit --source peepaw-cell --apply --repair
```

"(upper bound)" is printed on every non-zero count — the number is an upper
bound by construction (see gap-report.md §4) and must never read as exact.

## 2. Exit codes

Consistent with 005.

| Code | Meaning |
|---|---|
| `0` | Every audited source reconciled, or reported cleanly in report-only mode |
| `1` | At least one source `Incomplete` or `Unverified` |
| `2` | Config invalid, volume guard failed, or no such source |

## 3. `pull all` integration

Per source, after the existing pull and ingest:

1. Audit if `audit_state` is older than `audit_interval_days`, unless
   `--no-audit`. `--audit` forces it.
2. On `Incomplete` with `auto_repair` and `--apply`: repair if within budget,
   then re-audit.
3. Record the outcome in the summary line.

New flags: `--no-audit`, `--audit`.

**Summary vocabulary** — the existing status word gains a reconciliation clause:

```
Refresh summary
  IDLE     matt-personal    nothing new, covered through 2026-10-27, reconciled today
  OK       kat-icloud       copied 423 (1.63 GB), covered through 2026-10-27, reconciled 2026-10-20
  GAP      peepaw-cell      671 missing across 2 months — 2.5 GB, within budget
  UNVERIF  matt-public      audit could not complete: session expired
```

Two new statuses, `GAP` and `UNVERIF`, kept distinct from `FAILED` for the same
reason `IDLE` is distinct from it: "the pull worked and the archive has a hole"
is not "the pull failed".

## 4. Ranking of advice (FR-025)

The summary's closing advice is ordered by what blocks the operator. This fixes
a defect observed on 2026-10-26, where three sources needed re-authentication
and the headline advice was to sweep the one healthy source.

1. Sources needing re-authentication — name the `auth` command per source
2. Sources `UNVERIF` for other reasons
3. Sources `GAP` over budget — name the repair command
4. Sources never reconciled, or overdue for an unbounded sweep

At most the first non-empty category gets a command block; the rest are one
line each. The operator should never have to choose which of four suggestions
matters.

## 5. Interaction with `reconcile_interval_days`

`audit_interval_days` (7) governs the cheap audit. `reconcile_interval_days`
(30) continues to govern when an **unbounded sweep** is considered overdue.

A source reconciled by a clean audit has its `reconcile_state` advanced, so it
is no longer overdue for a sweep either — the audit satisfies the same
obligation more cheaply. In practice the 30-day sweep nag disappears for any
source that audits clean, which is the point of the feature. The summary MUST
NOT report a source as both "reconciled today" and "sweep overdue".
