# Specification Quality Checklist: Bounded, Honest iCloud Pulls

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-26
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`

### Validation record — 2026-09-26

Iteration 1: all items pass. Details on the judgement calls:

- **Implementation detail**: downloader flag names (`--recent`, `--until-found`,
  `--skip-created-before`) appear only inside the verbatim **Input** block, which
  records what the operator asked for. Every functional requirement is written
  against observable behaviour ("bound the number of items it examines",
  "MUST NOT advance the coverage watermark") rather than against a flag or a
  tool name. The external downloader is referred to by role in Assumptions, not
  by name.
- **SC-008 and FR-027** reference the automated suite and supported host
  platforms. Retained deliberately: the project constitution makes
  proven-by-test a release gate (Development Workflow & Quality Gates) and
  cross-platform parity a hard requirement, and features 001–004 state both the
  same way. These are project acceptance conditions, not design choices.
- **One clarification was resolved with the operator before writing** rather
  than left as a marker — the reconciliation trigger (2026-09-26 session). It
  was the only question where two reasonable answers produced materially
  different day-to-day behaviour.
- **One decision was settled by precedent rather than by asking**: whether
  working mirrors stay prunable. Feature 004's recorded clarification (~50 GB
  transient working volume; verified-archived staged media is prunable) already
  answers it, so the spec cites that precedent in Assumptions and treats the
  alternative as rejected. Reopening it is a spec amendment, not an open
  question.

### Risk carried into planning

(Superseded by the re-validation below, which restates and extends these risks
against the amended priority order.)

### Re-validation — 2026-09-26 (post-incident amendment)

Spec amended after a live coverage-loss incident. Re-ran all 16 items: all still
pass. What changed and why:

- **Priorities reordered.** Watermark integrity moved P3 → P1; bounded scan
  moved P1 → P3. Driver: the defect stopped being hypothetical. Two of four
  sources advanced their watermarks on 2026-09-26 having downloaded nothing,
  leaving a ~24-day hole (Peepaw Cell) and a ~31-day hole (Matt Public Cell)
  outside every future routine window. Secondary driver: a premature advance
  shortens the next window, so the performance work would have made the
  remaining bug *look* fixed.
- **Root cause added to Overview** with the catalog evidence table, and three
  contributing design properties named — exit-status-only success inference, an
  advance condition that passes on a null ingest result
  (`src/archivist/cli.py:828`), and no record of what an advance claimed.
- **New requirements**: FR-002 (positively confirm the download step rather
  than trusting exit status), FR-003 (null ingest result blocks advance),
  FR-007 (record the claimed coverage interval), FR-010 and FR-027 (a source
  that could not work is never reported as OK), FR-018 (targeted re-cover path
  for a known gap).
- **New success criteria**: SC-001 (zero silent advances) and SC-004 (the two
  lost intervals are re-covered and confirmed).
- **User Story 4 re-scoped.** Was pure cosmetics. The incident summary showed
  four sources as OK while two had done nothing, so "distinguish nothing-to-do
  from did-nothing" is now a correctness-adjacent requirement, not polish.

### Risks carried into planning

1. **FR-002 depends on an external signal that has not been verified.** The
   downloader must expose something positively confirmable — completion message,
   session artifact, item count. Assumptions names a fallback (pre-flight
   session validation plus post-run re-validation) if it does not. This must be
   resolved in `/speckit-plan`, because FR-002 carries the P1 story.
2. **The bounded scan still rests on the assumption that the downloader's
   recency bound terminates enumeration early** rather than filtering while
   walking the library — the same filter-mistaken-for-a-bound error this feature
   exists to fix. Verify empirically before building User Story 3 on it.
3. **SC-004 is an operator action, not code.** It will not be satisfied by
   implementation alone and must not be marked complete by an implementation
   run.

### Post-analyze remediation — 2026-09-26

`/speckit-analyze` reported 0 CRITICAL, 3 HIGH, 9 MEDIUM, 4 LOW. Four findings
were remediated; the rest are carried as recorded risks.

**Applied:**

- **F1 (HIGH)** — spec/contract contradiction on the null-ingest case. FR-003
  amended to permit an advance only when the proof shows a complete enumeration
  with zero items downloaded. Spec and `contracts/coverage-proof.md` §4.3 now
  agree. `research.md` R6 and the `plan.md` risk row updated from "proposed" to
  "applied".
- **C1 (HIGH)** — FR-002 promised confirmation that the download step
  "authenticated", which is not independently verifiable: icloudpd signals a
  credential failure by returning 1, which the existing `exit_code` check
  already refuses on, and `session_established()` only proves a cookie file
  exists, not that it is live. **FR-002 was narrowed** to promise only the
  completion evidence it can actually obtain, and a pre-flight session-artifact
  check was added whose stated purpose is failing fast (seconds instead of a
  six-minute enumeration), not proving authentication. New tasks T009/T014;
  `CoverageProof.session_present_before`, a fail-closed bullet, and contract
  test row 23 added. The spec's Assumptions entry was rewritten — it previously
  described this as an open planning question.
- **C2 (HIGH)** — FR-009 (preserve the 7-day window overlap) had zero task
  coverage while its callers were being rewritten. New task T026 extends the
  existing `tests/unit/test_pull_window.py`.
- **F2 (MEDIUM)** — `plan.md` and `tasks.md` both cited FR-017 (filing
  backdated items) where FR-026 (reporting) was meant. Corrected in both.

**Task list**: 65 → 68, renumbered. Validator confirms 68 sequential IDs, no
duplicates, no format violations, a file path in every description.

**Carried, not fixed** (accepted for now, listed so they are not rediscovered
as surprises): E1 (SC-006 has no verification task), E2 (FR-029's mirror
prunability clause has no regression test), E3 (FR-018's re-cover path is not
in user-facing docs), E4 (`--no-reconcile` has no backing FR), A1/A2
(FR-008/FR-026 and FR-010/FR-027 overlap), D1 (a `pull` dry-run still
downloads into staging — a pre-existing Principle II tension judged not a
violation, since the write is to the tool's own scratch under Principle I's
carve-out), B1 (SC-005's two-minute target is environment-dependent), F3
(`plan.md` says three existing test files will be extended; `tasks.md` creates
new files instead), F4/F5 (module cohesion and `pull_state` naming).

### Data-safety review — 2026-09-27 (task T063)

**Verdict: SAFE.** No data-loss or source-corruption path found. The reviewer
could not construct an input that modifies or deletes source data, writes
outside the archive/work volumes, mutates without `--apply`, records an
unverified copy as archived, or leaves a *premature* watermark. Every refusal
path probed fails in the safe direction (stale, not premature).

Verified clean: Principle I (single argv constructor, no mutating flag in any
mode, no shell so no flag injection), Principle II (every mutation inside
`if apply:`), Principles III/VI (ingest, dedupe, staging, catalog, guard,
hashing all unmodified), Principle IV ordering, Principle V (`_require` before
any mount access), and the core invariant across every mode and failure shape.

The reviewer also independently verified the enumeration-ordering assumption
the bounded-scan proof rests on — All Photos is ordered by capture date, newest
first — which is what makes one skip-before-cutoff observation sufficient.

**Fixed in response (all verified against upstream v1.32.3 source):**

- **F1, the serious one.** The stream parser was wrong about three of its five
  signals: it required a period after `already exists` (upstream emits none),
  matched present-tense `Downloading` for per-item events (upstream emits
  `Downloaded`), and recognised the preamble only in its N==1 wording. On any
  real multi-item run this counted the banner as a download and every genuine
  download as nothing, so a healthy quiet source with a pruned mirror would
  report FAILED forever and never advance — fail-closed, so nothing lost, but
  a hard functional break and exactly the widening-window outcome R6 set out to
  prevent. Root cause: the fixtures were written from guessed wording and the
  parser was then tested against the guesses, so 272 tests passed over it. Both
  preamble forms and the period-less `already exists` are now pinned, and
  `tests/fixtures/icloudpd_streams/README.md` records why.
- **F2** — an unreadable watermark was silently downgraded to "absent", which
  skipped the FR-005 span check. Now refused explicitly.
- **F3** — the journal was flushed but not fsynced, while the catalog commit is;
  a power cut between them could leave a watermark with no journal behind it.
  Now `os.fsync`.
- **F4** — `--since`/`--until` were parsed after ingest had already copied files.
  Now validated before anything runs.
- **F5** — a raising read loop (`| head`, a failing callback) left icloudpd
  blocked on a full pipe. Now killed.
- **F6** — `--full --since D` silently discarded the date. Now refused.
- **Doc correction** — `--recent` was described as bounding "most recently
  ADDED" items. It is capture-date ordered. Corrected in spec, research and
  code, with the dependency on that ordering now named beside
  `TESTED_ICLOUDPD_VERSIONS`.

**Carried, not fixed:** F7 — §4.3 tests mirror *presence* rather than comparing
counts (`ingest.copied + ingest.skipped >= proof.downloaded`). The reviewer
rated it an observation, not a defect, and the tighter rule is not safely
available while Live Photo pairs, asset grouping and noise filtering make the
two counts legitimately differ. Revisit with a rule that accounts for those.

Suite after remediation: **287 passing.**

### Second data-safety review — 2026-09-28 (ingest duplicate-check change)

**Verdict: UNSAFE as first written.** The reviewer reproduced a complete
only-copy-destruction chain, and it was my reasoning that was wrong, not just
my code.

**The defect.** The Principle III amendment justified settling the archived
side of a duplicate check from the catalog on the grounds that *"skipping
wrongly costs a copy that still exists in staging"*. That premise is false in
this codebase. `prune-staging` is what empties staging, and its primary branch
(`staging.py:99-109`) classified a staged file as deletable by hashing the
STAGED file, matching it to a catalog row, and checking only that the archived
file *existed* — it never read the archived bytes. The ingest re-read I removed
had been the sole byte gate standing in front of that delete.

Chain: an archived file rots in place at the same size → ingest settles the
duplicate from the catalog and skips → prune matches the same catalog row, sees
the file exists, deletes the staged good copy → the only good bytes are gone
and nothing is printed. Reproduced end to end.

The failure mode is worth naming beyond this instance: a safety property was
being relied on **across a module boundary**, with nothing in either module
recording the dependency. `staging.py`'s own fallback branch reads the archive
bytes and comments *"Stronger than the column check: it proves today's bytes"*
— the author knew the column check was weaker; the coupling just was not
written down anywhere the next change would see it.

**Fixed.** `staging.apply` now re-reads the archived counterpart before every
unlink and refuses on mismatch (`ARCHIVE_MISMATCH`, kept and reported, never
deleted). That is what Principle I's carve-out always required — "a
byte-verified archived copy is confirmed present AT THAT MOMENT" — and what the
primary branch had never done. The guarantee now lives at the deletion instead
of two modules upstream of it. Also fixed: F2 (a catalog caught lying about a
file can no longer settle that same file through another row), F3 (integrity
warnings reach `IngestOutcome`, and `pull all` no longer recommends
`prune-staging` after detecting rot), F4 (`--verify-archive` on all four ingest
entry points, was missing from `ingest-drops` and `pull all`), F5 (a zero spot
check rate is refused rather than silently disabling rot detection).

**Constitution corrected** in place, same day, before any applying use: the
false claim and the false premise are struck, with the correction recorded
rather than the original quietly edited away.

**Tests.** The reviewer showed three of my eight duplicate-check tests pinned
less than they claimed — most importantly, the one named "corrupted archive is
never skipped" passed `verify_archive=True`, so it proved a property of a flag
no default caller passes while reading as proof that the default was safe. It
is renamed to say what it pins, and the real path is now covered by
`tests/integration/test_ingest_prune_chain.py`, which asserts the whole chain:
ingest is fooled, prune's plan is fooled, and the unlink still refuses. Suite:
**313 passing**.

**No damage occurred.** Verified before fixing: the last prune ran 2026-09-28
11:00, before this change existed, and no `--apply` ingest ever ran on the fast
path.
