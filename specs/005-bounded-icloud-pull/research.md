# Phase 0 Research: Bounded, Honest iCloud Pulls

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

The spec carried three unknowns into planning, two of them load-bearing:
whether the downloader's recency option actually bounds enumeration (User
Story 3 rests on it), and whether the downloader exposes any positively
confirmable completion signal (FR-002, and therefore the P1 story, rests on
it). Both are resolved below against icloudpd v1.32.3 source. A third strand
re-examines the 2026-09-26 incident and corrects a root-cause hypothesis that
the source code disproves.

The locally installed icloudpd is a compiled Mach-O binary, so findings were
taken from the upstream source at the matching tag
(`icloud-photos-downloader/icloud_photos_downloader`, `v1.32.3`,
`src/icloudpd/base.py`) and cross-checked against the installed binary's
`--help` output and observed runtime behaviour.

---

## R1: Does `--recent N` bound enumeration, or only bound downloads?

**Decision**: It bounds enumeration. The bounded routine scan in User Story 3
is viable as specified.

**Finding**:

```python
if user_config.recent is not None:
    photos_count = user_config.recent
    photos_top: Iterable[PhotoAsset] = itertools.islice(
        photos_enumerator, user_config.recent
    )
else:
    photos_top = photos_enumerator
```

`itertools.islice` truncates the iterator itself. The downloader stops pulling
asset metadata from the service after N items; it does not fetch the whole
collection and then filter. This is the opposite of `--skip-created-before`,
which is evaluated per item inside the loop and therefore never terminates it.

**Why this mattered**: this is precisely the filter-versus-bound distinction
that caused the original problem, and the checklist flagged assuming it away
as a repeat of the same mistake. It is now established rather than assumed.

**Correction (2026-09-27, implementation review)**: an earlier draft of this
section and of the spec described `--recent` as bounding "the N most recently
ADDED items". That is wrong. The All Photos enumeration uses the list type
`CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted`, i.e. **capture/asset
date, newest first** — corroborated by the real 2026-09-26 stream, where
downloads of current items are followed by skips of items created 2025-01 in
strictly descending order. Two consequences: the bounded scan's blind spot for
recently-added-but-old media is not merely likely but structural; and the
§4.2 proof rule depends on this ordering, so a future icloudpd that changed it
would silently invalidate `reached_before_cutoff`. That dependency is now
named in `icloud.py` beside `TESTED_ICLOUDPD_VERSIONS`.

**Alternatives considered**:

- *`--until-found N`* — also terminates early, via an explicit `break` once N
  consecutive already-downloaded items are seen. Rejected as the routine
  primitive because it depends on the working mirror still holding previously
  downloaded files, and feature 004 established that mirrors are pruned. With
  a pruned mirror the counter never accumulates and the scan runs to the end
  of the library. It remains useful as an explicit operator flag and is
  retained.
- *Album-scoped scans* — narrowing to a smart album to reduce the walk.
  Rejected: album membership is user-curated and not guaranteed to contain new
  captures, so it trades a performance problem for a coverage problem.

---

## R2: Is there a positively confirmable completion signal? (FR-002)

**Decision**: Yes. The downloader emits an INFO-level completion message only
after its iteration finishes without cancellation. The plan parses the
downloader's output stream for it and treats its **absence** as "coverage not
proven".

**Finding**:

```python
message = f"All {photo_video_phrase} have been downloaded"
logger.info(message)
```

Emitted after all items in the selected scope are processed, and skipped when
the run was cancelled or when `--only-print-filenames` is active. The phrase
varies with what was requested — "All photos and videos have been
downloaded", "All photos have been downloaded", "All videos have been
downloaded" — so matching must tolerate the middle phrase.

Two supporting signals come from the same stream:

```python
logger.debug(skip_created_before_message(...))
#   -> "Skipping {filename}, as it was created {created}, before {cutoff}."
```

```python
logger.info(
    "Found %s consecutive previously downloaded photos. Exiting",
    user_config.until_found,
)
```

**Consequences for design**:

1. The completion message proves *the iteration ran to its end*, not *the
   whole library was scanned*. Under `--recent N` the iterator is truncated by
   `islice`, so the loop still ends normally and the message still appears.
   Completion alone is therefore **not** sufficient to prove a bounded scan
   covered its window.
2. Proving a bounded scan cleared its window needs a second signal: at least
   one `Skipping … before <cutoff>` line. Seeing one means enumeration reached
   an item older than the cutoff, so everything newer was examined. This is
   exactly the FR-022 determination.
3. That evidence is DEBUG-level, while FR-024 requires per-item narration to
   disappear from the operator's view. Both are satisfied by **capturing** the
   downloader's output at debug verbosity rather than letting it inherit the
   terminal, parsing it, and printing the tool's own summary. The verbosity
   flag (FR-025) passes the raw stream through.

**Alternatives considered**:

- *Trust the exit status* — status quo. Rejected: see R3; an exit status
  distinguishes a crash from a run, not a covered window from an uncovered
  one.
- *Pre-flight session validation only* (the fallback named in the spec's
  Assumptions) — check session validity before and after the run. Retained as
  a **supplement**, not the primary mechanism: it catches credential problems
  but says nothing about whether enumeration finished. Cheap enough to keep.
- *Count downloaded files in the mirror* — rejected outright. The mirror is
  prunable and carries no authoritative state (FR-029); a quiet source
  legitimately downloads nothing, so file counts cannot distinguish "nothing
  to do" from "did nothing".
- *`--only-print-filenames` probe before the real run* — a cheap "what's new"
  pre-check. Rejected as redundant once the output stream is parsed, and it
  doubles the enumeration cost.

**Risk accepted — log-text parsing is version-coupled.** These strings are not
a stable API. Mitigation is twofold: assert the downloader version at startup
and warn on an untested one; and **fail closed** — if the completion signal
cannot be found, the watermark does not advance. A future upstream rewording
therefore degrades to "runs stop advancing the watermark and say why", which
is noisy and visible, never silent and lossy. That failure direction is the
whole point of the feature and is recorded here as a deliberate choice.

---

## R3: What the downloader's exit status actually means

**Decision**: Exit status is necessary but nowhere near sufficient, and a
previously stated root cause for the 2026-09-26 incident is **withdrawn**.

**Finding**: the upstream code returns `0` on successful authentication, list
operations, and successful download; and `1` on login/MFA failure, unknown
library, service unavailable, and connection errors. There are no bare
`sys.exit()` calls; integer codes are returned to the caller.

**Correction**: during the incident analysis it was suggested that the
download step had exited `0` despite an expired session — by analogy with the
interactive authentication path, where `icloud.auth()` deliberately refuses to
trust a clean exit without confirming a session cookie on disk ("icloudpd can
exit 0 without doing anything"). The source does not support that for the
download path: a clean authentication failure returns `1`, which
`_pull_one` already handles by reporting `download-failed` and **not**
advancing the watermark. The comment in `auth()` remains accurate for the
`--auth-only` path it guards; it does not generalise as claimed.

**What survives the correction**: the defect and the damage are unchanged, and
so is the design conclusion. See R4.

---

## R4: The 2026-09-26 incident — what is established, and what is not

**Established from the catalog and shell history:**

| Fact | Evidence |
|---|---|
| All four sources' watermarks read ~2026-08-26 20:00 before the day's runs | last ingest run before today is `20260826-*`; no invocation between 2026-08-27 and 2026-09-26 |
| Each source's window that morning was therefore "since 2026-08-19" | watermark − 7-day overlap |
| Two sources were covered | `matt-personal` ingested 26 items captured 2026-08-27→09-23; `kat-icloud` ingested 324 captured 2026-08-28→09-25 |
| Two sources were not | `matt-public` and `peepaw-cell` ingested nothing; `matt-public`'s newest archived capture is still 2026-08-26 |
| All four watermarks nevertheless advanced to 2026-09-26 | `meta` rows `pull_state:*` |
| The advance was demonstrably premature for at least one source | the 14:03 run, now windowed to "since 2026-09-19", found and copied 15 `peepaw-cell` items captured 2026-09-20→24 — items that sat inside the earlier run's much wider window and were not fetched |
| The mirrors were empty going in | `prune-staging --apply` ran 2026-08-27 09:31 |

**Not established**: the precise failure mode that produced a non-failing run
which fetched nothing. Shell history records two `pull all --apply`
invocations today (13:34:40, 14:03:51), but zsh appends history on shell exit,
so invocations from a still-open shell — including the expired-credential
event the operator describes — may be absent. The observed watermark
timestamps (13:50:08–13:51:02) do not fall in configured source order, which
is consistent with more invocations than history shows. Forensic
reconstruction was abandoned as unnecessary: the design conclusion does not
depend on which member of the class occurred.

**Design conclusion (unchanged by R3)**: nothing anywhere in the pipeline
verifies that the download step covered its window. Coverage is inferred from
(a) a process exit status and (b) the absence of ingest failures — and
`src/archivist/cli.py:828` also passes when ingest produced *no result at
all*, because the guard short-circuits on a null. Any failure mode that
produces "exit 0, nothing fetched" advances the watermark, and nothing records
what the advance claimed, so the loss is unobservable afterwards. Rather than
hunt the specific trigger, the plan replaces inference with proof (R2) and
makes every advance self-describing (FR-007).

---

## R5: Where the coverage record lives

**Decision**: journal the coverage record to the run manifest first, then
mirror the latest into the catalog's `meta` table for fast reads.

**Rationale**: Constitution Principle IV makes files plus manifests
authoritative and the catalog a derived index that must remain rebuildable.
Watermarks are already operational state in `meta` (established by feature
004) and are not reconstructible from media files, so they stay there. The new
*coverage record* — what interval an advance claimed and what counts backed it
— is audit history, which belongs in the append-only journal. Writing the
journal entry before the `meta` update also keeps the ordering the
constitution requires.

**Alternatives considered**:

- *A new `pull_runs` table as the system of record* — rejected: it would put
  non-rebuildable audit history in the derived index, inverting Principle IV.
  A table may still be added later as a queryable projection of the journal.
- *`meta` only* — rejected: single-row-per-source overwrite loses exactly the
  history an audit needs.

---

## R6: Distinguishing a quiet source from a broken one

**Decision**: use the coverage proof, not the item count — and refine FR-003
accordingly. **Applied 2026-09-26** via `/speckit-analyze` finding F1; the spec
now carries the amended wording.

**Problem found during planning**: FR-003 as written says a run whose ingest
stage produced no result MUST NOT advance the watermark. Taken literally this
breaks a legitimate case: a genuinely quiet source downloads nothing, the
mirror stays empty, `_run_ingest` returns `None`, and the source would become
permanently unable to advance — its window widening forever.

**Resolution**: the discriminator is the coverage proof from R2, not the
presence of files. A run may advance on a null ingest result **only when** the
proof shows a complete enumeration that covered the window and reported zero
items to download. Without that proof, a null result blocks the advance, which
is the incident case FR-003 was written for.

**Proposed FR-003 amendment**: *"A run whose ingest stage produced no result
MUST NOT advance the coverage watermark unless the download step's coverage
proof shows a complete enumeration of the requested window with zero items
downloaded."* Recorded here rather than silently implemented. `/speckit-analyze`
raised it as finding F1 and the amendment is now in spec.md (FR-003), so spec
and contract agree.

---

## R7: Defaults

**Decision**: scan bound 500 items per source; reconciliation interval 30
days. Both configurable per source.

**Rationale**: measured rates from the catalog over the Aug–Sep window —
`matt-public` ~200 items per two weeks, `kat-icloud` ~80–160, `peepaw-cell`
~36, `matt-personal` ~35 — put the busiest source near 400/month. A 500-item
bound clears a month of the busiest source's additions, so weekly or
fortnightly operation has substantial headroom, and FR-023 makes an
undersized bound self-reporting rather than lossy. The 30-day reconciliation
interval matches the operator's observed cadence and bounds worst-case
staleness to roughly one month.

**Note**: the default bound is deliberately larger than needed for the current
libraries. The cost of an oversized bound is seconds of extra enumeration; the
cost of an undersized one is a refused advance and a re-run. Asymmetric, so
the default errs high.
