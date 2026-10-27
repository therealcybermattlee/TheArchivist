# Feature Specification: Reconciliation by Enumeration Diff

**Feature Branch**: `006-reconcile-by-diff`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "Cheap reconciliation by enumeration diff — replace the full re-download sweep with a listing pass diffed against the catalog, so the archive only pays for transfers when something is provably missing."

## Context

Feature 005 made coverage *provable*: a watermark only advances when the run can
demonstrate it covered its window. It left one obligation unpriced.

A coverage watermark is a claim about **created** time, but a cloud photo library
is **mutable in created time**. An asset created in 2019 and added to the library
today is filtered out by "skip items created before `<watermark>`", and by every
future run, because the watermark only moves forward. Such *backdated additions*
— scanned prints, shared-album saves, old-device imports, re-imported export
bundles — are not an edge case for a family archive; they are much of the point
of one. Reconciliation is the only mechanism that re-examines ground already
claimed.

Today reconciliation is a full re-download sweep. Because the working mirror is
pruned after every run, the downloader has no local copy to compare against and
refetches the entire library: roughly 246 GB across the four accounts, several
hours, against a working volume budgeted at ~50 GB. The September 2026 round
re-downloaded ~49,000 assets to discover **19** genuinely new files.

That cost is paid unconditionally, every interval, whether or not anything is
missing. The operator therefore disabled automatic reconciliation and now
receives a recurring prompt instead. Neither branch is satisfactory: the prompt
has to be read and acted on by hand, and re-enabling escalation would let a
routine refresh silently begin a multi-hour transfer that would overrun the
working volume.

The insight this feature rests on: **asking what is missing is cheap; fetching it
is expensive.** The archive already records, permanently, the identity of every
item it has ever filed. The library can be listed without transferring media.
Comparing the two answers the reconciliation question outright, and most of the
time the answer is "nothing", at a cost of no bytes at all.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prove a source complete without downloading it (Priority: P1)

The archivist asks whether a source is fully archived. The tool lists what the
library holds, compares it against what the archive has filed, finds no
difference, and records the source as reconciled — having transferred no media.

**Why this priority**: This is the feature. It converts reconciliation from an
unconditional multi-hour cost into a question that is usually answered for free,
and it is the only story that must exist for the feature to deliver value. The
remaining stories refine what happens when the answer is *not* "nothing".

**Independent Test**: Point the tool at a source whose archive is known complete.
It reports the source reconciled, advances the reconciliation watermark, and
records zero media transferred.

**Acceptance Scenarios**:

1. **Given** a source whose archived holdings match its library, **When** the
   archivist runs an audit with `--apply`, **Then** the reconciliation watermark
   advances, a journal record is written naming what was compared, and no media
   is transferred.
2. **Given** the same source, **When** the archivist runs an audit without
   `--apply`, **Then** the result is reported and no watermark moves.
3. **Given** a source whose listing cannot be completed, **When** the audit runs,
   **Then** it refuses to claim reconciliation, names why, and leaves the
   watermark untouched.
4. **Given** a source whose stored credentials are not usable, **When** the audit
   runs, **Then** it refuses before contacting the provider and names the source.

---

### User Story 2 - See what is missing, and where it clusters (Priority: P2)

When the comparison does find a difference, the archivist learns how many items
are missing and which periods they fall in, as a short report — not as a prompt
to begin a multi-hour transfer, and not as something to be reconstructed from
raw logs.

**Why this priority**: Without this, a non-empty result is only an alarm. The
archivist's next decision — repair a few date ranges, or accept a full sweep —
depends entirely on whether the gaps are clustered or scattered, and nothing
else in the system can answer that.

**Independent Test**: Seed a catalog missing a known contiguous span, run the
audit, and confirm the report names the correct count and the correct period,
without a transfer.

**Acceptance Scenarios**:

1. **Given** a source missing a contiguous span of items, **When** the audit
   runs, **Then** the report states the number missing and the periods they fall
   in, ordered by period.
2. **Given** a source missing items scattered across many periods, **When** the
   audit runs, **Then** the report says so plainly rather than listing every
   period individually.
3. **Given** any audit result, **When** it completes, **Then** the full list of
   items judged missing is retained for inspection, not only summarized.

---

### User Story 3 - Repair a gap by fetching only the gap (Priority: P3)

Having seen where items are missing, the archivist repairs the source. The tool
fetches only the periods that contain missing items, rather than the library.

**Why this priority**: This is where the saved bandwidth is actually realized,
but it depends on P1 and P2 having identified the gap, and the archivist can
already repair a known gap by hand using existing commands.

**Independent Test**: Seed a known gap, run the repair, and confirm the transfer
is bounded to the affected periods and that the archive afterwards contains the
missing items.

**Acceptance Scenarios**:

1. **Given** an audit that found items missing within a bounded set of periods,
   **When** the archivist runs the repair with `--apply`, **Then** only those
   periods are fetched and the items are filed.
2. **Given** a repair that completes and leaves nothing missing on re-audit,
   **When** it finishes, **Then** the reconciliation watermark advances.
3. **Given** a repair that completes but leaves items still missing, **When** it
   finishes, **Then** the reconciliation watermark does **not** advance and the
   remainder is reported.
4. **Given** gaps too scattered for period-bounded repair to help, **When** the
   archivist runs the repair, **Then** the tool says a full sweep is the
   remaining option and does not begin one on its own.

---

### User Story 4 - Keep every source honest without being asked (Priority: P4)

The routine refresh audits each source as part of its normal work, so a gap
surfaces on the next run rather than at the next interval.

**Why this priority**: The highest-value outcome — the two-month gap would have
surfaced the next day — but it is a change to the default behaviour of the most
frequently used command, so it should land only once the audit it depends on is
proven in isolation.

**Independent Test**: Run the routine refresh against a source with a seeded gap
and confirm the gap is reported in the summary without a separate command.

**Acceptance Scenarios**:

1. **Given** a routine refresh across all sources, **When** it completes, **Then**
   each source's summary line states whether it is reconciled and, if not, how
   many items are missing.
2. **Given** a routine refresh, **When** any source's audit cannot be completed,
   **Then** that source is reported as unverified and the others still complete.
3. **Given** a routine refresh, **When** it completes, **Then** its worst-case
   media transfer is bounded and stated, with no branch that can begin an
   unbounded transfer unprompted.

---

### Edge Cases

- **Un-filed items in the working mirror.** The listing step omits items the
  working area already holds. If such an item has not yet been filed into the
  archive, it appears in neither the listing nor the archive inventory, and a
  naive comparison would conclude "nothing missing" when something is. This is
  the one failure direction that loses coverage, and the audit MUST NOT be able
  to reach a "complete" verdict while un-filed items are present.
- **An item filed under a different recorded path.** An item recognized on
  arrival as a duplicate of something already archived may be recorded against
  the earlier path, so the listing's path for it finds no match. It is reported
  missing although its bytes are archived — an over-report, which is the safe
  direction.
- **Name collisions resolved by suffix.** The provider's collision handling can
  alter the filename it would write, so the same item can be named differently
  across runs and appear missing. Also an over-report.
- **A listing that ends early.** A listing interrupted, truncated, or ended
  without its completion signal proves nothing and MUST NOT be read as an empty
  difference.
- **Provider wording changes.** The listing and its completion signal come from
  an external tool whose output format is not a contract. Unrecognized output
  MUST degrade to a refusal, never to a silent "nothing missing".
- **An empty source.** A library with no items yields an empty listing, which is
  a legitimate complete result only when the listing itself completed.
- **Unusable credentials.** The audit MUST refuse before contacting the provider,
  so an audit can never contribute to an account lockout.
- **A period containing both missing and present items.** Repairing by period
  re-fetches items already held; these are recognized and discarded rather than
  re-filed, at a bandwidth cost that MUST be reported before the repair begins.
- **Items whose period cannot be determined.** An item the listing places outside
  any recognizable period MUST be reported rather than silently dropped from the
  comparison.
- **A source never previously reconciled.** Its first audit is an ordinary audit,
  not a special case, and may reconcile it outright if nothing is missing.

## Requirements *(mandatory)*

### Functional Requirements

#### The audit

- **FR-001**: The system MUST be able to determine what a source's library
  contains without transferring media.
- **FR-002**: The system MUST compare that listing against the archive's own
  permanent record of what it has filed for that source, and MUST NOT rely on
  the contents of transient working storage to decide what is archived.
- **FR-003**: The comparison MUST be reported as a count of items judged missing,
  grouped by the period they fall in.
- **FR-004**: The system MUST retain the full list of items judged missing for
  operator inspection, not only the summary.
- **FR-005**: The audit MUST be available as an explicit operator action against
  a single named source.
- **FR-006**: The audit MUST default to reporting only, and MUST require an
  explicit apply before any stored state changes (Principle II).

#### Fail-closed verdicts

- **FR-007**: An empty difference MUST be treated as proof of completeness ONLY
  when the listing itself completed. An incomplete, truncated, or unrecognized
  listing MUST produce a refusal naming the reason.
- **FR-008**: The audit MUST NOT reach a "complete" verdict while the source's
  working area holds items that have not been filed into the archive.
- **FR-009**: The comparison MUST be designed so that its errors over-report
  missing items and never under-report them. Where a judgement is uncertain, the
  item MUST be judged missing.
- **FR-010**: The audit MUST verify the source's stored credentials are usable
  before contacting the provider, and MUST refuse by name if they are not.
- **FR-011**: Every refusal MUST state which source it concerns and what would
  make it succeed.

#### Reconciliation

- **FR-012**: A completed audit finding nothing missing MUST be sufficient to
  advance the source's reconciliation watermark, with no media transfer.
- **FR-013**: An audit finding anything missing MUST NOT advance the
  reconciliation watermark.
- **FR-014**: Advancing the reconciliation watermark MUST write a durable journal
  record first, recording what was compared, how many items were listed, how many
  were judged missing, and the resulting verdict (Principle IV).
- **FR-015**: The coverage watermark and the reconciliation watermark MUST remain
  independent; an audit MUST NOT advance the coverage watermark, which continues
  to require a covered window.

#### Repair

- **FR-016**: When items are judged missing, the system MUST be able to fetch only
  the periods containing them, rather than the whole library.
- **FR-017**: Before fetching, the system MUST state how many items it expects to
  fetch and how many of those are expected to be already held.
- **FR-018**: A repair MUST re-audit on completion, and MUST advance the
  reconciliation watermark only if nothing remains missing.
- **FR-019**: When missing items are too scattered for period-bounded repair to
  be worthwhile, the system MUST say so and MUST NOT begin a full sweep on its
  own initiative.
- **FR-020**: Repair MUST never modify the source library (Principle I).

#### Routine integration

- **FR-021**: The routine refresh MUST audit a source as part of its normal work
  when that source has not been audited within the audit interval, and MUST
  report each source's reconciliation state in its summary.
- **FR-021a**: The audit interval MUST be configurable per deployment and MUST
  default to **7 days**, chosen so a gap surfaces within a week while most
  routine refreshes remain fast.
- **FR-021b**: The summary MUST state, for each source, when it was last
  reconciled and whether this run audited it.
- **FR-022**: A source whose audit cannot be completed MUST be reported as
  unverified without preventing the other sources from completing.
- **FR-023**: No branch of the routine refresh may begin an unbounded media
  transfer without an explicit operator instruction; the worst-case transfer of a
  routine refresh MUST be bounded and stated.
- **FR-024**: The operator MUST be able to skip auditing for a given run, and to
  force an audit regardless of the interval.

#### Budgeted self-repair

- **FR-027**: When a routine refresh's audit finds missing items, the system MUST
  repair them automatically if the expected transfer is within the repair budget,
  and MUST report rather than fetch when it is not.
- **FR-028**: The repair budget MUST be configurable per deployment and MUST
  default to a value small enough that an automatic repair cannot overrun the
  working volume. Where the estimate exceeds it, the summary MUST state the
  estimate, the budget, and the command that would repair it anyway.
- **FR-029**: The expected transfer MUST be estimated before any fetch begins and
  MUST be derived from the items judged missing, not assumed.
- **FR-030**: Where the estimate cannot be made, the system MUST treat the repair
  as exceeding the budget rather than attempting it.
- **FR-031**: An automatic repair MUST obey every rule a manual repair obeys:
  dry-run semantics where not applying, journal before state change, re-audit
  before advancing the reconciliation watermark, and no unbounded fallback.
- **FR-032**: The operator MUST be able to disable automatic repair entirely,
  reducing the behaviour to report-only.

#### Legibility

- **FR-025**: Where a source needs operator action, the summary MUST rank that
  above routine advice, naming the action.
- **FR-026**: The audit MUST report progress while running, since listing a large
  library takes minutes with no other visible sign of activity.

### Key Entities

- **Library listing**: What a source's library currently holds, as the set of
  items the provider would deliver, obtained without transferring media. Carries
  its own completeness signal; without it the listing is evidence of nothing.
- **Archive inventory**: The archive's permanent record of items already filed for
  a source. Survives the pruning of working storage, which is what makes the
  comparison possible at all.
- **Gap report**: The outcome of one comparison — items judged missing, grouped by
  period, with the full list retained. Deliberately an upper bound.
- **Repair plan**: The set of periods a repair would fetch, with the expected
  transfer volume and the expected proportion already held.
- **Reconciliation verdict**: Reconciled, incomplete (with a gap report), or
  unverified (with a reason). Only the first may advance the watermark.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A source holding 35,000 items can be confirmed complete with **zero
  media transferred**, where the present behaviour transfers the entire library.
- **SC-002**: Confirming a complete source takes under 30 minutes per source and
  consumes no working storage beyond its report.
- **SC-003**: A gap of the kind that went undetected for 61 days (2026-08-26 to
  2026-10-26) is surfaced within **7 days** of its appearance under routine use.
- **SC-004**: Repairing a gap confined to two periods transfers under 10% of what
  a full sweep of that source would transfer.
- **SC-005**: Across the full test suite, no case exists in which the audit
  reports fewer missing items than are genuinely missing.
- **SC-006**: Every audit outcome is legible from the summary alone — count
  missing and where — with no need to read raw provider output.
- **SC-007**: Every branch of the routine refresh has a stated worst-case media
  transfer, and none can exceed it without an explicit operator instruction.
- **SC-009**: A routine refresh that audits and finds nothing missing adds no
  media transfer to that run, and a routine refresh that repairs within budget
  transfers no more than the configured budget.
- **SC-010**: Across a typical week, the number of routine refreshes that pay
  listing cost is at most one per source.
- **SC-008**: An audit run against a source with unusable credentials makes no
  authentication attempt, measured by the absence of any provider sign-in.

## Assumptions

- **The external downloader can list without transferring.** Verified against the
  version in use: it exposes a listing mode that prints the target path of every
  item it would fetch and transfers no media. Behaviour of other versions is not
  assumed; an unrecognized version degrades to a refusal, consistent with 005.
- **Listed paths and recorded paths are directly comparable.** Verified: the
  archive records, for each filed item, the identical path string the listing
  produces. Comparison is made on the path relative to the source's working area,
  so an absolute-path change cannot masquerade as a missing item.
- **The archive's record outlives working storage.** Records of filed items are
  retained permanently and are unaffected by pruning, which is what allows a
  pruned source to be audited at all.
- **Listing cost is time, not bandwidth.** Listing is a sequence of provider
  queries, empirically 10–20 minutes for 30,000–40,000 items, consuming no
  meaningful storage. This is the feature's recurring cost and is accepted.
- **Repair granularity is the period, not the item.** The downloader accepts date
  bounds but not an explicit list of items, so a repair is expressed as periods
  and will re-fetch already-held items within them. Where gaps are scattered
  across more than **eight** periods, period-bounded repair is treated as not
  worthwhile and the operator is told so (FR-019); eight is a starting value,
  revisable once measured.
- **Over-reporting is acceptable and under-reporting is not.** Duplicate-path and
  collision-suffix effects inflate the missing count. The cost is a redundant
  fetch that is recognized and discarded; the alternative risks losing coverage.
- **Scheduled operation remains out of scope.** This feature is a *precondition*
  for unattended operation by making every branch bounded, but the constitution
  reserves scheduled/unattended operation for its own feature and constitutional
  review (Scope & Boundaries). Nothing here enables it.
- **Reconciliation interval semantics are unchanged.** The existing watermark is
  reused; this feature changes only what makes a reconciliation *legitimate*,
  not what one means.
- **Two operator decisions, taken 2026-10-27.** (1) The routine refresh audits on
  a **7-day** interval rather than on every run: auditing all four sources every
  time would add roughly an hour to the most frequently used command, most of it
  spent proving nothing is wrong, and a week is a tolerable worst case against
  the 61 days actually experienced. (2) A gap found during a routine refresh is
  **repaired automatically within a budget**, falling back to reporting when the
  estimate exceeds it — which keeps every run bounded while still realizing the
  saved bandwidth. The budget defaults to **5 GB**, comfortably inside the
  working volume and large enough for an ordinary missed window; it is a starting
  value, revisable once measured.

## Dependencies

- Feature 005's coverage watermarks, run modes, coverage proof, advance decision,
  and fsynced coverage journal, which this feature extends rather than replaces.
- The per-account credential validity check introduced alongside 005, which gates
  the audit (FR-010).
- The archive's permanent per-item record of filed source paths.

## Out of Scope

- Scheduled or unattended execution (reserved by the constitution).
- Detecting items deleted from the source library; this compares the library
  against the archive in one direction only, and the archive never deletes to
  match a source (Principle I).
- Re-verifying the bytes of already-archived files, which remains the job of the
  archive scan.
- Changing how coverage windows are computed or how the coverage watermark
  advances.
