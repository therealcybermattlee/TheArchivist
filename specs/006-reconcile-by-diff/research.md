# Phase 0 Research: Reconciliation by Enumeration Diff

All findings below are empirical unless marked otherwise. The primary evidence
is 6,100 lines of real `--only-print-filenames` output captured from the
`matt-public` library on 2026-10-26 before the run was cancelled, plus the four
live cookie jars and the production catalog. Nothing here rests on reading
upstream documentation alone — 005 was burned exactly that way, when a parser
was written against guessed wording and 272 tests passed over it.

---

## R1. What `--only-print-filenames` actually emits

**Decision**: Treat stdout as a stream of absolute target paths, one per line,
and treat any line that does not begin with the source's mirror prefix as a log
line rather than an item.

**Evidence**: Of 6,100 captured lines from a successful run, **6,100 began with
the mirror prefix** — no banner, no summary, no progress, no completion line.
The paths are byte-identical in form to what the catalog stores:

```
/Volumes/ExternalBaseUnit/TheArchivist/staging/icloud/matt-public/2026/10/IMG_1001.HEIC
```

Against `assets.original_path` from the production catalog:

```
/Volumes/ExternalBaseUnit/TheArchivist/staging/icloud/matt-public/2026/07/IMG_0825.MOV
```

Same shape, same `--folder-structure {:%Y/%m}`, same root. Direct comparison is
sound.

**Rationale**: A positive prefix test is the only safe discriminator, because of
R2.

**Alternatives considered**: Parsing every line as a path and filtering later —
rejected; it would silently absorb an error line as an item and inflate the
"present" side, which is the under-reporting direction.

---

## R2. Errors arrive on stdout, interleaved with items

**Decision**: The enumeration parser must scan for failure signals in the same
stream it reads paths from, and any failure signal makes the listing incomplete.

**Evidence**: The three sources whose sessions had expired wrote their error to
**stdout**, not stderr, even at `--log-level error`:

```
enum-kat-icloud.txt:  2026-10-26 19:10:18 ERROR    Authentication required for Account. (421)
```

stderr held only an unrelated multiprocessing shutdown warning. A naive reader
that captured stdout and counted lines would have seen "1 item listed" for a
library of 33,000 and concluded almost everything was missing — or, with the
polarity reversed, concluded a one-item library was complete.

**Rationale**: This is the single most dangerous finding of Phase 0. It means
"the process exited and we have some lines" is not evidence of a listing. Only
an explicit completeness signal is.

---

## R3. There is no completion line, so completeness needs another signal

**Decision**: A listing is complete when the process **exits 0**, emits **no
failure signal**, and its **final line is a well-formed path** (not truncated
mid-line). All three required; any shortfall is `Unverified`.

**Evidence**: `--only-print-filenames` suppresses the ordinary run's
`All photos and videos have been downloaded` line — none appears in 6,100
captured lines. The 005 parser's primary completeness signal is therefore
unavailable here.

**Rationale**: Fail-closed. An `Unverified` audit costs a repeat; a falsely
`Reconciled` one re-creates the September loss, where an unproven claim became a
watermark.

**Alternatives considered**: Comparing the listed count against the catalog's
count for the source as a sanity bound — rejected as a *completeness* signal
(the counts legitimately differ) but retained as a reported diagnostic.

---

## R4. A listed path is not a unique asset key

**Decision**: Deduplicate the listing before comparison, and document the gap
count as an upper bound on items rather than an exact asset count.

**Evidence**: 6,100 lines held 6,087 unique paths. The 13 duplicates occur as
**adjacent pairs**:

```
line 5937  2025/07/IMG_0691.HEIC
line 5938  2025/07/IMG_0691.MOV
line 5939  2025/07/IMG_0691.HEIC   <- different asset, same target path
line 5940  2025/07/IMG_0691.MOV
```

Two distinct iCloud assets that would be written to one local path. At fetch
time `--file-match-policy name-size-dedup-with-suffix` resolves this by
appending a size suffix, so the archive holds them under names the listing never
produces.

**Consequence**: such items are reported missing even when archived — an
over-report, the safe direction, at a rate of roughly 0.2% (13 in 6,100).

---

## R5. Enumeration order is by date added, not date created

**Decision**: Make no ordering assumption. Group the *missing* set by month after
the comparison, never during it.

**Evidence**: The first 6,100 listed items span 2025/08 through 2026/10, with
2025/10 (683) and 2026/03 (666) more heavily represented than recent months.
Ordering follows the library's added order, which is why 005's `--recent N`
bound truncates by recency-of-addition rather than by date.

**Rationale**: A streaming "stop when we reach month X" optimisation would be
incorrect, and a partial listing cannot be salvaged into a partial verdict.

---

## R6. The catalog side is cheap and already correct

**Decision**: Select `original_path` for the source's mirror prefix, compare on
the path relative to that prefix.

**Evidence**: The production catalog holds ~97,000 rows across six source
labels. A prefix-filtered `original_path` query is index-free but trivial at this
size; the comparison itself is Python set arithmetic over ~40,000 strings per
source, well under the 2-second budget.

Prefix filtering is also a correctness requirement, not an optimisation: all
four accounts share one staging tree, and an unfiltered query would let one
account's rows satisfy another's audit — the identical defect that made the
session pre-flight unfailable.

**Relative-path keying** guards against a work-volume path change (a remount
under a different name) presenting the entire library as missing.

---

## R7. Items in the mirror are invisible to the listing

**Decision**: Refuse a `Reconciled` verdict while the source's mirror holds files
not recorded in the catalog.

**Evidence**: Upstream documents the flag as printing filenames "not including
files that are already downloaded". A file sitting in the mirror is therefore
absent from the listing; if it has not yet been filed it is also absent from the
catalog. It would appear on neither side and the diff would read empty.

**Rationale**: This is the only identified path to a **false `Reconciled`**, so
it gets an explicit guard (FR-008) rather than relying on operators pruning
first. In normal operation the mirror is pruned and this is a no-op.

---

## R8. Repair granularity, and the size estimate

**Decision**: Express repairs as `--skip-created-before` / `--skip-created-after`
month ranges. Estimate transfer as `missing_count × median archived file size for
that source`; where no median exists, treat the estimate as exceeding the budget.

**Evidence**: icloudpd accepts no item list, only date bounds. The listing
carries no sizes. The catalog holds `file_size` per archived row, making a
per-source median available for every source that has ever filed anything.

Observed density on the live run: 1,269 files over two months cost 4.83 GB
(~3.8 MB/file). A 5 GB budget therefore covers roughly 1,300 files — comfortably
more than a missed month on the busiest source (Kat, ~280 assets/month).

**Scatter cutoff**: 8 distinct months, a starting value. Beyond that the ranges
approximate a full sweep and the operator is told so rather than being committed
to one (FR-019).

---

## R9. The session gate is already built

**Decision**: Reuse `icloud.session_status(session_dir, username)` unchanged as
the precondition for enumeration.

**Evidence**: Added 2026-10-27 after a locked account. It reads the account's
cookie jar locally, requires an unexpired `X-APPLE-WEBAUTH-TOKEN`, and makes no
network call — verified against all four live accounts, correctly identifying
three valid and one dead.

**Rationale**: SC-008 demands an audit make no authentication attempt against
unusable credentials. Since an audit is meant to run weekly and unattended-ish,
an audit that could contribute to a lockout would be worse than no audit.

---

## R10. Version pinning

**Decision**: Reuse 005's `TESTED_ICLOUDPD_VERSIONS` gate. An untested version
degrades the audit to `Unverified`.

**Rationale**: Consistent with 005, and the stakes are the same — this feature
reads an external tool's output to decide whether a coverage claim may be made.
R2 and R3 are precisely the kind of undocumented behaviour that changes between
releases without notice.

---

## Fixture provenance

`tests/fixtures/icloudpd_streams/enumeration-sample.log` is derived from the
captured `matt-public` run. Real filenames are replaced with synthetic ones; the
**shape** is preserved — the `{:%Y/%m}` folder structure, HEIC+MOV live-photo
pairing, the added-order month spread, and the colliding duplicate pair from R4.
No family filenames or identifiers are committed.
