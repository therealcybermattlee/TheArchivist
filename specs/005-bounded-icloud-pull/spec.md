# Feature Specification: Bounded, Honest iCloud Pulls

**Feature Branch**: `005-bounded-icloud-pull`

**Created**: 2026-09-26

**Status**: Draft

**Input**: User description: "Make routine iCloud pulls fast and correct. Today
`archivist pull all` bounds each source's pull only with icloudpd's
`--skip-created-before` date filter, which is a filter and not a scan bound:
icloudpd enumerates the entire All Photos collection for every source on every
run, emitting thousands of DEBUG 'Skipping X, as it was created ... before ...'
lines, so a routine refresh spends most of its wall-clock scanning past items it
will never download. Three problems to solve: (1) bound the routine scan so
enumeration stops early instead of walking the whole library, while keeping a
reconciliation path that still catches items added recently but created long
ago; (2) quiet icloudpd's default debug log level so the run's real progress is
legible; (3) close a correctness gap where a deliberately narrow pull
(--recent N / --until-found N with --apply) advances the per-source pull
watermark to now, silently creating a permanent coverage gap between the old
watermark and the narrow slice actually fetched — the watermark must only
advance when the run genuinely covered [last_watermark, now]. Also in scope:
decide and document how the persistent icloudpd mirror under
staging/icloud/<source> interacts with `prune-staging`, since pruning the mirror
destroys icloudpd's already-downloaded skip mechanism and is what makes the date
filter load-bearing in the first place."

**Amended 2026-09-26** after the coverage-loss incident recorded below, which
converted the watermark defect from a theoretical narrow-pull hazard into the
feature's primary driver and re-ordered the user stories accordingly.

## Overview

Two problems live in the same code path, and until 2026-09-26 only the noisy one
was visible.

**The visible one**: a routine refresh is supposed to be the cheap, frequent
operation. Today each configured cloud source is asked for "items created since
the coverage watermark", but that instruction is a *filter applied while walking
the entire library*, not a *bound on the walk*. With four cloud sources and
roughly 100,000 catalogued assets, a refresh with three new photos to fetch
still examines every asset in every account and narrates each rejection at debug
verbosity. The operator cannot tell working from wedged.

**The expensive one**: the coverage watermark can advance past ground the run
never covered, and once it does, the skipped interval is outside every future
routine window — permanently, and silently. A watermark is the tool's claim
about what is safely archived. Today that claim is inferred from a process exit
code, and a cloud download step that authenticates badly, transfers nothing, and
exits cleanly is indistinguishable from a source that simply had nothing new.

The second problem is why this feature exists in its current shape. The first is
why the operator noticed.

### Incident: 2026-09-26 coverage loss

A routine multi-source refresh ran while the operator's cloud credentials were
in an expired state. For two of four sources the download step produced nothing
and reported success; ingest then found only already-archived files in the
working mirror, recorded zero failures, and the watermark advanced to the
present for both. A re-run under valid credentials an hour later used the
freshly-advanced watermark, so its window reached back only seven days.

The damage is measurable in the catalog:

| Source | Newest archived capture | Items archived 2026-08-26 → 2026-09-19 | Typical rate |
|--------|------------------------|-----------------------------------------|--------------|
| Kat Cell | 2026-09-25 | 203 | ~80 / 2 weeks |
| Matt Personal Cell | 2026-09-23 | 24 | ~35 / 2 weeks |
| **Peepaw Cell** | 2026-09-24 | **0** | ~36 / 2 weeks |
| **Matt Public Cell** | **2026-08-26** | **3** (all on 08-26) | ~200 / 2 weeks |

Two sources hold a roughly 24-day and a roughly 31-day hole. Both now carry a
watermark of 2026-09-26, so no future routine refresh will ever ask for that
interval. The media is still in iCloud and is recoverable by an explicit
back-dated pull, but nothing in the tool would have reported the loss, and
nothing in the tool would have healed it.

Three properties of the current design combined to produce this:

1. Success is inferred from the download step's exit status alone. The codebase
   already knows this is untrustworthy — the interactive authentication path
   deliberately refuses to believe a clean exit without confirming a session
   artifact on disk, with the comment "icloudpd can exit 0 without doing
   anything" — but the download path extends no equivalent skepticism.
2. The advance condition (`src/archivist/cli.py:828`) treats "ingest reported no
   failures" as proof of coverage. An ingest that copied nothing passes it. An
   ingest that never ran at all — because the mirror was empty — also passes it,
   since the guard short-circuits on a null result.
3. Nothing records *what interval a watermark advance claimed to cover*, so a
   genuinely quiet week and an unverified month look identical afterwards.

### What this feature does

It makes the watermark mean something: it advances only on positively confirmed
coverage, it records what it claimed, and it says so out loud. It adds a
self-scheduling reconciliation sweep that both covers the bounded scan's
structural blind spot and repairs holes like the two above without the operator
having to know they exist. It then makes the routine path bounded, so its cost
tracks what changed rather than what exists. And it makes the output legible.

The safety model does not move. Sources stay read-only, nothing is deleted from
any cloud account, dry-run remains the default, archive copies are still
verified before the catalog records them.

## Clarifications

### Session 2026-09-26

- Q: Bounding the routine scan can miss items added recently but created long
  ago. How should the unbounded reconciliation sweep that covers that blind spot
  be triggered? → A: Auto-escalate when stale. Each source carries its own
  last-reconciled watermark; a routine refresh automatically performs the full
  sweep for any source whose watermark is older than a configured interval
  (default 30 days) and reports plainly that it is doing so. No separate command
  to remember, and the slow run happens roughly once a month per source.

- Q: A full sweep re-downloads the whole library, because the mirror is
  pruned — ~246 GB across the four accounts, against a working volume budgeted
  at ~50 GB in feature 004. Should sweeps still be automatic? → A (2026-09-28,
  **amends the auto-escalation answer above**): No. Sweeps are
  operator-scheduled, one source at a time with a prune between, keeping peak
  working storage at the largest single source (~114 GB) rather than the sum.
  A new `auto_reconcile` setting governs this; escalation is still the code
  default (FR-012), and this deployment sets it false. Critically, suppressing
  escalation must never suppress the *reporting*: a run still names every
  overdue source and the command to sweep it, so switching this off cannot
  hide a growing gap. FR-012 is amended accordingly; FR-014's announcement
  requirement now applies to the overdue report as well as to the sweep.

- Q: After the coverage-loss incident, should watermark integrity still sit
  behind the performance work? → A: No. Reordered to P1. Fixing the watermark
  first is also a prerequisite rather than a preference: a premature advance
  narrows the next window, which makes runs *look* faster, so shipping the
  bounded scan first would mask the remaining coverage bug rather than expose
  it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A watermark means what it says (Priority: P1)

As the family archivist, I trust that a source's coverage watermark reflects
media that is actually in the archive. A run that could not do its job — expired
credentials, a download step that transferred nothing, a deliberately narrow
slice — leaves the watermark alone and tells me why, so the interval it failed
to cover stays on the list of things to fetch.

**Why this priority**: This is the defect that cost real coverage on 2026-09-26
and would have done so silently and indefinitely. Everything else in this
feature is time and comfort; this is whether the tool's central claim is true.
It is also a prerequisite: a premature advance shortens the next window, so
performance work layered on top would disguise the remaining loss.

**Independent Test**: Record a source's coverage watermark, run an applying pull
under conditions that prevent the download step from doing its job, and confirm
the watermark is unchanged, the source is reported as failed rather than OK, and
a subsequent routine refresh still requests the full uncovered interval.

**Acceptance Scenarios**:

1. **Given** a source whose credentials or session are not valid, **When** an
   applying pull runs, **Then** the coverage watermark does not advance, the
   source is reported as failed with the reason, and the run does not describe
   the source as OK.
2. **Given** a download step that exits successfully, **When** the run cannot
   positively confirm that the step authenticated and completed its enumeration,
   **Then** the coverage watermark does not advance and the run says what could
   not be confirmed.
3. **Given** a run whose ingest stage produced no result at all because the
   working mirror was empty, **When** the run completes, **Then** the coverage
   watermark does not advance.
4. **Given** an applying pull bounded by an item count, by an already-found
   threshold, or by an explicit end date, **When** it completes, **Then** the
   coverage watermark does not advance and the run names the bound that
   prevented it.
5. **Given** an applying pull requesting everything from a start date at or
   before the previous watermark, with no upper bound and no scan bound,
   **When** it completes successfully, **Then** the coverage watermark advances.
6. **Given** a run that begins at time T and finishes at T+n, **When** the
   coverage watermark advances, **Then** it advances to T, so items created
   during the run are still sought next time.
7. **Given** any watermark advance, **When** it is recorded, **Then** the
   interval claimed and the counts observed are recorded with it.
8. **Given** a narrow or failed pull that left the watermark in place, **When** a
   routine refresh runs afterwards, **Then** it requests the full interval since
   the original watermark.

---

### User Story 2 - Holes get found and filled without my knowing they exist (Priority: P2)

As the family archivist, I do not audit my own archive for gaps. The tool
notices that a source has not been completely reconciled in a while, performs a
full sweep on its own schedule, tells me it is doing so and why, and files
whatever it finds — whether that is a folder of old scans imported last week or
a month of my father's photographs that an earlier run quietly skipped.

**Why this priority**: This is the only mechanism that repairs coverage after
the fact. User Story 1 stops new holes forming; it does nothing about the two
that already exist. It is also what makes User Story 3 safe, since a bounded
recency scan structurally cannot see recently-added-but-old media.

**Independent Test**: Set a source's reconciliation watermark older than the
configured interval, place in the source both an item whose capture date
predates the coverage watermark and an item inside a known uncovered interval,
run a routine refresh, and confirm the tool announces the sweep and files both.

**Acceptance Scenarios**:

1. **Given** a source whose last reconciliation is older than the configured
   interval, **When** a routine refresh runs, **Then** the tool announces before
   scanning that this source is due, states how long it has been, and warns the
   run will take longer.
2. **Given** a source with an interval that a previous watermark advance never
   actually covered, **When** a reconciliation sweep runs, **Then** the items in
   that interval are downloaded and filed.
3. **Given** a reconciliation sweep that completes successfully in applying
   mode, **When** the run finishes, **Then** that source's reconciliation
   watermark advances and subsequent refreshes return to the bounded path.
4. **Given** a reconciliation sweep that fails or encounters ingest errors,
   **When** the run finishes, **Then** neither watermark advances and the source
   remains due.
5. **Given** an item added to a source whose capture date predates the coverage
   watermark, **When** the next reconciliation sweep runs, **Then** it is filed
   by its capture date like any other item.
6. **Given** a multi-source refresh in which one source is due for
   reconciliation, **When** the run proceeds, **Then** the other sources still
   take the bounded path and a failure in the sweeping source does not stop
   them.

---

### User Story 3 - A routine refresh costs what changed, not what exists (Priority: P3)

As the family archivist, I run the routine refresh across all my cloud sources.
When little or nothing has been added since my last run, it finishes in well
under a minute per source, because it stops looking once it has examined a
bounded slice of the most recently added items — instead of walking every asset
in the account to reject it.

**Why this priority**: This is the reported pain and the reason the routine
operation is avoided rather than run often; frequent small pulls are the
project's stated operating model. It sits behind the integrity work because it
would otherwise mask it, not because it matters less to daily use.

**Independent Test**: With a source whose new-item count is zero, run a routine
refresh and confirm it terminates after examining no more than the configured
bound, reports the number examined, and completes in bounded time — then repeat
against a source with a handful of new items and confirm those are fetched.

**Acceptance Scenarios**:

1. **Given** a cloud source with no items added since the coverage watermark,
   **When** a routine refresh runs, **Then** it examines at most the configured
   scan bound, downloads nothing, and reports the count examined and elapsed
   time.
2. **Given** a cloud source with a small number of newly added items, **When** a
   routine refresh runs, **Then** every one of those items is downloaded and
   ingested, and the scan still stops at the bound.
3. **Given** four configured cloud sources, **When** a routine refresh runs
   across all of them, **Then** total cost is bounded by four scan bounds, not
   by four library sizes.
4. **Given** the working mirror for a source has been pruned since the last run,
   **When** a routine refresh runs, **Then** it does not re-download items that
   are already archived and predate the coverage watermark.
5. **Given** a source receiving more new items between runs than its scan bound
   allows, **When** the bounded scan ends without reaching past the coverage
   watermark, **Then** the watermark does not advance, the run reports the bound
   may be too small, and it names the setting to raise.

---

### User Story 4 - I can tell what the run is doing (Priority: P4)

As the family archivist, I watch a refresh and can see, per source, which path
it took, how much it examined, how much it downloaded, whether its watermark
advanced, and how long it took — without reading thousands of per-item rejection
lines. When I need that detail for troubleshooting, one flag brings it back.

**Why this priority**: Pure legibility — except for one part that is not. The
2026-09-26 incident reported four sources as OK while two of them had done
nothing. A summary that cannot distinguish "nothing to do" from "did nothing" is
part of how the loss went unnoticed.

**Independent Test**: Run a refresh and confirm the per-source output is a small
number of summary lines with no per-item narration, that each line states
whether the watermark advanced, and that the verbosity flag restores full
detail.

**Acceptance Scenarios**:

1. **Given** a routine refresh at default verbosity, **When** it runs, **Then**
   per-item skip narration is absent from the output.
2. **Given** a refresh at default verbosity, **When** each source completes,
   **Then** the output states the path taken, items examined, downloaded, and
   skipped, elapsed time, and whether the coverage watermark advanced.
3. **Given** a source that did nothing because it could not, **When** the
   summary prints, **Then** it is visually distinct from a source that did
   nothing because there was nothing to do.
4. **Given** a troubleshooting need, **When** the operator supplies the
   verbosity flag, **Then** the underlying per-item detail is restored in full.
5. **Given** a completed multi-source refresh, **When** the summary prints,
   **Then** the operator can tell from it alone which sources are fully covered,
   which are due for reconciliation, and which need a re-run.

---

### Edge Cases

- **A download step transfers nothing.** Legitimate for a quiet source, and the
  signature of a failed one. The tool must distinguish these by positively
  confirming the step authenticated and completed enumeration — not by counting
  bytes, and not by trusting an exit code.
- **Credentials expire mid-run, partway through a multi-source refresh.**
  Sources already completed keep their advances; the failing source and every
  source after it must not advance, and the summary must make the boundary
  obvious.
- **The bound is hit and the window was not cleared.** The run must recognise it
  stopped early without proving it reached past the watermark, refuse to
  advance, and report that the bound looks too small for this source's rate of
  change.
- **First run on a host with no coverage watermark.** Unchanged: the tool
  refuses a stateless full pull and directs the operator to a deliberate
  bootstrap. A missing *reconciliation* watermark is treated as immediately due,
  so the bootstrap doubles as the first reconciliation.
- **The mirror was pruned between runs.** Expected and supported. The routine
  path must not read an empty mirror as "nothing has ever been downloaded", and
  must not read it as proof of successful coverage either.
- **Reconciliation and routine work collide.** A source due for reconciliation
  gets the sweep instead of, not in addition to, the bounded scan.
- **Clock skew and items created mid-run.** The existing overlap subtracted from
  the coverage watermark remains; combined with advancing to run-start, an item
  created in flight is still sought next time.
- **Reconciliation falls due for several sources at once.** The run announces
  each up front, so a long run is predicted rather than discovered.
- **An item is added to a cloud source and removed before any sweep.** Out of
  scope; the tool archives what it observes and never deletes from a source.

## Requirements *(mandatory)*

### Functional Requirements

#### Coverage watermark integrity

- **FR-001**: A source's coverage watermark MUST advance only when the run
  demonstrably covered the whole interval from the previous watermark to the
  run's start.
- **FR-002**: The system MUST NOT infer download-step success from its exit
  status alone. Before a watermark may advance, the run MUST positively confirm
  that the download step completed its enumeration of the requested window,
  from evidence the step itself emitted. Authentication is evidenced by the
  step's own failure signalling and is not separately verifiable by this tool;
  a credential problem MUST therefore surface as a refused advance by way of
  the completion check, never as a successful one.
- **FR-003**: A run whose ingest stage produced no result — including because
  the working mirror held no files — MUST NOT advance the coverage watermark,
  unless the download step's coverage proof shows a complete enumeration of
  the requested window that reported zero items to download. A genuinely
  quiet source is proven empty, never assumed empty.
- **FR-004**: A run bounded by an item count, by an already-found threshold, or
  by an explicit end date MUST NOT advance the coverage watermark.
- **FR-005**: A run requesting everything from an explicit start date at or
  before the previous watermark, with no upper bound and no scan bound, MAY
  advance the coverage watermark.
- **FR-006**: When the coverage watermark advances, it MUST be set to the time
  the run started, not the time it finished.
- **FR-007**: Each watermark advance MUST record the interval it claims to
  cover and the counts observed, so a later audit can distinguish a genuinely
  quiet interval from an unverified one.
- **FR-008**: Every applying run MUST state, per source, whether the coverage
  watermark advanced and — when it did not — which specific condition prevented
  it.
- **FR-009**: The existing overlap subtracted from the coverage watermark when
  computing a routine window MUST be preserved.
- **FR-010**: A source whose run could not do its work MUST be reported as
  failed, never as successful-with-nothing-to-do.

#### Reconciliation

- **FR-011**: The system MUST track, per source, when that source was last
  reconciled by a complete unbounded scan, stored separately from the coverage
  watermark.
- **FR-012**: A routine refresh MUST perform a complete unbounded scan for any
  source whose last reconciliation is older than a configured interval, in place
  of that source's bounded scan — **unless escalation is disabled by
  configuration** (amended 2026-09-28). When it is disabled, the refresh MUST
  still evaluate staleness and MUST still report every overdue source together
  with the command that sweeps it. Suppressing the sweep never suppresses the
  warning.
- **FR-013**: The reconciliation interval MUST be configurable, with a
  documented default of 30 days.
- **FR-014**: Before beginning a reconciliation sweep, the system MUST announce
  which source is being reconciled, how long it has been, and that the run will
  take longer than a routine one.
- **FR-015**: A source's reconciliation watermark MUST advance only after a
  complete unbounded scan that ran in applying mode, whose download step was
  positively confirmed per FR-002, and which produced no ingest failures.
- **FR-016**: A source with no recorded reconciliation watermark MUST be treated
  as due for reconciliation.
- **FR-017**: A reconciliation sweep MUST file items whose capture dates predate
  the coverage watermark, using the same date-based placement as any other
  ingest.
- **FR-018**: The system MUST provide a documented path to re-cover a specific
  known-uncovered interval for one source without re-pulling its entire library,
  for use when a gap is already known.

#### Bounding the routine scan

- **FR-019**: A routine refresh MUST bound the number of items it examines per
  source and stop examining once that bound is reached.
- **FR-020**: The scan bound MUST be configurable per source, with a documented
  default suited to typical family-phone rates of change.
- **FR-021**: A routine refresh MUST continue to avoid re-downloading items
  already archived that predate the coverage watermark, so a pruned working
  mirror does not cause the window's content to be fetched again.
- **FR-022**: A routine refresh MUST determine whether its bounded scan reached
  past the coverage watermark, and MUST report that determination.
- **FR-023**: When a bounded scan ends without demonstrably reaching past the
  coverage watermark, the run MUST NOT advance the coverage watermark, MUST
  report that the bound may be insufficient, and MUST name the setting to raise.

#### Legibility

- **FR-024**: At default verbosity, the download step MUST NOT emit per-item
  rejection narration.
- **FR-025**: The system MUST provide a flag that restores full per-item detail
  for troubleshooting.
- **FR-026**: For each source, a run MUST report the path taken (bounded or
  reconciling), items examined, downloaded, and skipped, elapsed time, and
  whether the coverage watermark advanced.
- **FR-027**: The end-of-run summary MUST visually distinguish a source that had
  nothing to do from one that could not do its work.
- **FR-028**: The end-of-run summary MUST let the operator determine, without
  scrolling back, which sources are fully covered, which are due for
  reconciliation, and which need a re-run.

#### Mirror lifecycle

- **FR-029**: Per-source working mirrors MUST remain prunable by the existing
  guarded prune command; the routine pull MUST NOT depend on mirror contents
  surviving between runs, and MUST NOT treat mirror contents as evidence of
  coverage.
- **FR-030**: The documented role of the working mirror MUST be corrected to
  describe it as transient pass-through storage rather than a persistent record
  of what has been downloaded.

#### Safety and scope preservation

- **FR-031**: All commands touched by this feature MUST remain dry-run by
  default, requiring an explicit apply on the same invocation to write.
- **FR-032**: No code path introduced by this feature may modify or delete
  anything in a cloud source.
- **FR-033**: Automated tests MUST cover: each condition that blocks a
  coverage-watermark advance, including an unconfirmed download step and a null
  ingest result; the watermark recording run-start rather than run-end; the
  recorded coverage interval; reconciliation triggering on a stale watermark and
  not on a fresh one; the reconciliation watermark advancing only on a clean
  confirmed sweep; the bounded scan terminating at its bound; and the
  insufficient-bound detection refusing to advance.

### Key Entities

- **Coverage watermark**: Per source, the point in time through which the
  archive is believed complete. Drives the routine window. Advances only on
  positively confirmed coverage.
- **Coverage record**: What a watermark advance claimed — the interval covered
  and the counts observed — retained so gaps can be audited after the fact.
- **Reconciliation watermark**: Per source, when that source last received a
  complete unbounded scan. Independent of the coverage watermark; drives
  auto-escalation and after-the-fact repair.
- **Scan bound**: Per source, the maximum number of recently-added items a
  routine refresh will examine before stopping.
- **Reconciliation interval**: How stale a reconciliation watermark may become
  before the next routine refresh escalates that source to a full sweep.
- **Source mirror**: Transient per-source working storage media passes through
  on its way to the archive. Prunable at any time; carries no authoritative
  state and is never evidence of coverage.
- **Run outcome**: Per source, the path taken, counts observed, whether each
  watermark advanced, and — when one did not — why.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero silent coverage advances. Under any condition that prevents a
  source's download step from doing its work, the coverage watermark is
  unchanged and the source is reported as failed — verified by exercising
  invalid-credential, empty-mirror, and no-result conditions.
- **SC-002**: A narrow pull followed by a routine refresh retrieves every item
  created since the pre-narrow watermark — zero items lost to a watermark that
  advanced past uncovered ground.
- **SC-003**: Zero permanent coverage gaps. For any item present in a cloud
  source, at most one reconciliation interval passes before it is archived —
  verified by placing items that no date-windowed or recency-bounded scan would
  find and confirming the next sweep files them.
- **SC-004**: The two intervals lost in the 2026-09-26 incident are re-covered
  and confirmed present in the archive, and a reconciliation sweep run
  afterwards finds nothing further missing in them.
- **SC-005**: A routine refresh across all configured cloud sources, with no new
  media in any of them, completes in under two minutes total.
- **SC-006**: Routine refresh time is independent of total library size: adding
  50,000 archived items to a source does not measurably lengthen its routine
  refresh.
- **SC-007**: The number of items a routine refresh examines per source is
  capped at that source's configured bound and is reported, so the operator can
  confirm the cap held.
- **SC-008**: A routine refresh produces at most ten lines of output per source
  at default verbosity, versus thousands today.
- **SC-009**: From the end-of-run summary alone, the operator can correctly
  state for every source whether it is fully covered and what to run next —
  confirmed by inspection against the recorded watermarks and coverage records.
- **SC-010**: The full automated suite passes on both supported host platforms
  with no new platform-specific skips.

## Assumptions

- **Cloud downloads continue to go through the existing external downloader.**
  This feature changes how that tool is invoked, and how much its reports are
  trusted; it does not replace it or add a second cloud integration.
- **The downloader emits a positively confirmable completion signal.**
  Established in planning (research R2): an INFO-level completion message
  emitted only after the iteration finishes without cancellation. FR-002 rests
  on that plus a pre-flight session-artifact check whose purpose is failing
  fast, not proving authentication. Authentication itself is not independently
  verifiable by this tool — the downloader signals a credential failure through
  a non-zero exit, which the completion check already refuses on — and FR-002
  was narrowed on 2026-09-26 to promise only what can be proven.
- **The downloader can bound its own enumeration by a count of recently-added
  items.** User Story 3 depends on this; if the available bounding mechanism
  does not terminate enumeration early in practice, planning must find that out
  before the bounded path is built on it.
- **Enumeration is ordered by CAPTURE date, newest first** — corrected
  2026-09-27 during implementation review; the earlier wording here said "when
  an item was added", which is wrong. The conclusion is unchanged and in fact
  stronger: an item captured long ago but added today sorts to the far end of
  the enumeration, so a bounded scan cannot reach it and the date filter would
  exclude it anyway. That is the blind spot reconciliation exists to cover.
  The ordering is also load-bearing for the bounded-scan proof: it is what
  makes a single "skipped, created before the cutoff" observation evidence that
  everything newer was examined.
- **Working mirrors stay prunable.** Feature 004 recorded the decision that the
  working volume is a small transient pass-through (~50 GB) and that
  verified-archived staged media is prunable. This feature accepts that as
  settled, which is what forces the routine path to stay correct without relying
  on mirror contents. The alternative — retaining mirrors permanently so the
  downloader can skip what it already holds — is rejected on that precedent.
- **Default scan bound of 500 items per source, default reconciliation interval
  of 30 days.** Both are starting points chosen to sit comfortably above
  observed rates of change; both are configurable, and FR-023 makes a too-small
  bound self-reporting rather than silently lossy.
- **Reconciliation is automatic by default but may be operator-scheduled.**
  Amended 2026-09-28: the 2026-09-26 clarification chose auto-escalation before
  the download volume was quantified. Once it was (~246 GB for one pass, against
  a ~50 GB working budget), this deployment switched to operator-scheduled
  sweeps via `auto_reconcile: false`. `--full` on a single source is the sweep;
  FR-018's `--since` remains the targeted re-cover path for a known gap. The
  bounded-sweep design that would make automatic sweeps affordable regardless of
  library size — date-sliced, pruning between slices — was considered and
  deferred to its own feature rather than bolted on here.
- **Recovery of the 2026-09-26 holes is operational, not automatic.** The
  feature provides and documents the means (FR-018); re-covering those two
  specific intervals is an operator action and is tracked by SC-004 rather than
  performed by the code.
- **Existing bootstrap behaviour is unchanged.** A source with no coverage
  watermark still refuses a stateless full pull and requires a deliberate
  bootstrap.
- **One applying host at a time.** Watermarks remain per-host catalog state,
  consistent with the constitution's scope boundary.
- **Ingest, dedupe, dating, placement, and verification are untouched.** This
  feature governs what reaches the ingest engine and what the tool claims about
  coverage — not how media is hashed, dated, filed, or verified.
