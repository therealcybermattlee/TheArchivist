# Contract: `archivist pull` command surface

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

Defines the operator-facing surface after this feature: flags, output shape,
and exit codes. Existing flags keep their names and meanings; what changes is
what the tool does with the result and what it prints.

---

## 1. `archivist pull all`

```
archivist pull all [--apply] [--verbose] [--show N] [--stop-on-error]
                   [--no-reconcile] [--config PATH]
```

| Flag | Status | Behaviour |
|---|---|---|
| `--apply` | unchanged | Write to the archive and to state. Dry-run otherwise. |
| `--verbose` | NEW | Pass the downloader's raw per-item output through. Default suppresses it (FR-024/FR-025). |
| `--show N` | unchanged | Sample rows per source. |
| `--stop-on-error` | unchanged | Abort at the first failing source. |
| `--no-reconcile` | NEW | Never escalate to a sweep this run, even if a source is due. The summary still reports which sources are overdue. Escape hatch for "I need this run to be fast." |
| `--config PATH` | unchanged | |

Per source, the mode is resolved as: due for reconciliation and not
`--no-reconcile` → `RECONCILE`; otherwise `ROUTINE_BOUNDED`. Sources with no
coverage watermark are reported as needing a bootstrap and skipped, unchanged.

## 2. `archivist pull icloud`

```
archivist pull icloud --source KEY [--recent N] [--since DATE] [--until DATE]
                      [--until-found N] [--full] [--no-download]
                      [--apply] [--verbose] [--show N] [--config PATH]
```

All existing flags retain their names and downloader semantics. Mode
resolution follows [data-model.md](../data-model.md) §4. The behavioural change
is that `--recent`, `--until-found` and `--until` now resolve to `NARROW` and
can no longer advance the coverage watermark — which is the defect this
feature exists to close.

**`--since` is the repair tool.** `--since D` with no upper bound and no count
bound resolves to `EXPLICIT_SINCE` and may advance the watermark, but only when
`D <= previous watermark`; a `--since` that starts *after* the current
watermark would silently skip the span between, and is refused with that span
named.

## 3. Output

### 3.1 Per-source, default verbosity

At most ten lines (SC-008). No per-item narration.

```
=== [1/4] matt-personal ===
  routine: bounded scan (500), items created since 2026-09-19
  examined 500, downloaded 12, already present 0          [00:14]
  ingest: copied 12 (0.4 GB), skipped 0, failed 0
  coverage advanced -> 2026-09-26 13:34:40
```

Reconciling:

```
=== [2/4] matt-public ===
  reconciliation due (last swept 2026-08-24, 33d ago) — this will take longer
  full sweep, items created since 2026-08-19
  examined 39,932, downloaded 3, already present 0        [06:21]
  ingest: copied 3 (0.01 GB), skipped 0, failed 0
  coverage advanced -> 2026-09-26 13:41:02
  reconciled through 2026-09-26 13:41:02
```

Refusing:

```
=== [3/4] kat-icloud ===
  routine: bounded scan (500), items created since 2026-09-19
  examined 500, downloaded 500, already present 0         [02:07]
  ingest: copied 500 (8.1 GB), skipped 0, failed 0
  coverage NOT advanced: scan bound (500) reached without clearing the
    window — raise scan_bound for this source; next run re-covers from
    2026-09-19
```

### 3.2 Summary

Must distinguish "nothing to do" from "could not work" (FR-027) and state
coverage per source (FR-028).

```
Refresh summary
  OK       matt-personal    copied 12 (0.40 GB), covered through 2026-09-26
  OK       matt-public      copied 3 (0.01 GB), covered + reconciled 2026-09-26
  PARTIAL  kat-icloud       copied 500 (8.10 GB), coverage held at 2026-08-26
                            scan bound reached — raise scan_bound, then re-run
  IDLE     peepaw-cell      nothing new, covered through 2026-09-26
  FAILED   john-cell        download step could not be confirmed

  reconciliation due: kat-icloud (41d)
  next: archivist pull all --apply
```

Status vocabulary:

| Status | Meaning |
|---|---|
| `OK` | Work done, coverage advanced. |
| `IDLE` | Nothing new, coverage advanced — proven empty window, not an assumption. |
| `PARTIAL` | Work done, coverage **not** advanced; reason given and the interval stays owed. |
| `FAILED` | Could not do its work. Coverage unchanged. |
| `BOOTSTRAP` | No coverage watermark; needs an explicit `--full`. |

`IDLE` versus `FAILED` is the distinction whose absence let the 2026-09-26 loss
pass unnoticed: both printed as `OK ... copied 0`.

## 4. Exit codes

| Code | Condition |
|---|---|
| 0 | Every source `OK`, `IDLE`, or `PARTIAL`. |
| 1 | Any source `FAILED` or `BOOTSTRAP`. |
| 2 | Configuration or guard rejection before any source ran (unknown source, wrong type, missing username, unmounted volume). |

`PARTIAL` is deliberately **not** a failure exit: the run did real work and
refused to over-claim. It is visible in the summary and the operator decides
whether to raise the bound. Making it exit non-zero would train the operator to
ignore a non-zero exit.

## 5. Behaviour explicitly unchanged

- Dry-run remains the default everywhere; `--apply` is required for any write,
  and approval never carries across invocations.
- A dry-run `pull` still performs downloads. Pre-existing, documented, out of
  scope.
- Volume guards (`_require`) run before any source is touched.
- A failing source does not stop the others unless `--stop-on-error`.
- `auth icloud` is untouched.
- No deletion path is reachable from any `pull` command.
