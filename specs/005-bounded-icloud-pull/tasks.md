---

description: "Task list for 005-bounded-icloud-pull"
---

# Tasks: Bounded, Honest iCloud Pulls

**Input**: Design documents from `/specs/005-bounded-icloud-pull/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: REQUIRED, not optional. FR-033 enumerates the mandatory cases and the
project constitution (Development Workflow & Quality Gates) makes
proven-by-test a release gate for anything touching state that represents what
is archived. Test tasks are written to fail first.

**Organization**: Grouped by user story. Story priorities follow the
post-incident order in spec.md: integrity (P1) → reconciliation (P2) → bounded
scan (P3) → legibility (P4).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different file, no dependency on incomplete work
- **[Story]**: US1–US4, on user-story phase tasks only

## Path Conventions

Single project: `src/archivist/`, `tests/` at repository root.

**Same-file serialization note**: much of this feature lands in two files
(`src/archivist/icloud.py`, `src/archivist/cli.py`). Tasks touching the same
file are deliberately **not** marked `[P]` even when logically independent.
`[P]` counts are therefore lower than a task list of this size usually shows;
that is accurate, not an oversight.

---

## Phase 1: Setup

**Purpose**: unblock the spec discrepancy and lay down fixtures and constants

- [X] T001 Resolve the FR-003 wording discrepancy in `specs/005-bounded-icloud-pull/spec.md` per [research.md](research.md) R6 — amend to *"…MUST NOT advance the coverage watermark unless the download step's coverage proof shows a complete enumeration of the requested window with zero items downloaded"*. Spec edit only, no code. **BLOCKS T029.** Prefer running `/speckit-analyze` first and letting it drive this edit.
- [X] T002 [P] Record icloudpd output fixtures under `tests/fixtures/icloudpd_streams/` — `complete-unbounded.log` (real capture), `complete-bounded.log` (real capture with `--recent`), `until-found-exit.log`, `auth-failure.log`, `truncated-midline.log`. Real captures come from a `--dry-run` against a live source; the failure cases are synthesized from the formats documented in [contracts/coverage-proof.md](contracts/coverage-proof.md) §2. Redact Apple IDs.
- [X] T003 [P] Add `TESTED_ICLOUDPD_VERSIONS` (initially `{"1.32.3"}`) and `probe_version() -> str | None` to `src/archivist/icloud.py`
- [X] T004 [P] Add `pull_journal_path(run_id)` returning `logs_dir / f"pull-{run_id}.jsonl"` to `src/archivist/config.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the capture-and-parse plumbing every story depends on. US1 owns
the *decision*; this phase owns the *evidence*.

**⚠️ CRITICAL**: no user story work begins until this phase is complete.

### Tests (write first, confirm failing)

- [X] T005 [P] Failing unit tests for stream-signal parsing in `tests/unit/test_coverage_proof.py` — contract cases 1, 2, 6 from [contracts/coverage-proof.md](contracts/coverage-proof.md) §6, driven from the T002 fixtures
- [X] T006 [P] Failing unit tests for fail-closed conditions in `tests/unit/test_coverage_proof_failclosed.py` — contract cases 3, 4, 5
- [X] T007 [P] Failing unit tests for `PullMode` resolution in `tests/unit/test_pull_mode.py` — every row of [data-model.md](data-model.md) §4, including each `NARROW` trigger
- [X] T008 [P] Failing unit tests for the journal writer in `tests/unit/test_coverage_journal.py` — record shape per [data-model.md](data-model.md) §3, append-only, flush-per-write, invariants from §2
- [X] T009 [P] Failing unit tests for pre-flight session validation in `tests/unit/test_session_preflight.py` — an absent session directory and an empty session directory both refuse before the downloader is invoked; a present artifact proceeds. FR-002, contract case 23.

### Implementation

- [X] T010 Replace `subprocess.run(cmd)` with streaming line capture in `icloud.download()` in `src/archivist/icloud.py` — read stdout/stderr continuously to avoid pipe deadlock, always pass `--log-level debug`, yield lines to a consumer callback
- [X] T011 Add the `CoverageProof` frozen dataclass to `src/archivist/icloud.py` per [contracts/coverage-proof.md](contracts/coverage-proof.md) §3
- [X] T012 Implement `parse_stream()` in `src/archivist/icloud.py` — recognise all six signals in §2, tolerate the three completion phrasings, count `examined`/`downloaded`/`already_present`
- [X] T013 Implement the fail-closed rules in `src/archivist/icloud.py` per §3.1 — untested version, non-zero exit, no completion and no until-found exit, truncated stream all set `parser_confident=False` with a populated `notes` — FR-002
- [X] T014 Implement the pre-flight session check in `src/archivist/icloud.py` — evaluate `session_established()` before building the argument list, set `CoverageProof.session_present_before`, and return a fail-closed proof naming the session directory rather than invoking the downloader. Fails fast: a dead session costs seconds, not a full enumeration. FR-002.
- [X] T015 [P] Create `src/archivist/coverage.py` with the `PullMode` enum and `resolve_mode()` per [data-model.md](data-model.md) §4
- [X] T016 Add the `CoverageRecord` dataclass and `append_record()` journal writer to `src/archivist/coverage.py` — write-then-flush, one JSON object per source per run
- [X] T017 Replace `_run_ingest`'s bare `None` return with an `IngestOutcome` type in `src/archivist/cli.py` that distinguishes `not-a-directory` / `no-files` / `ran(copied, skipped, failed)`, so a caller can tell "nothing to ingest" from "ingest never ran"
- [X] T018 Thread a `verbose: bool` through `icloud.download()` and its callers in `src/archivist/icloud.py` and `src/archivist/cli.py` — raw lines pass through when true, are consumed silently when false

**Checkpoint**: the tool can now prove what a download step did. Nothing acts on that proof yet.

---

## Phase 3: User Story 1 — A watermark means what it says (Priority: P1) 🎯 MVP

**Goal**: a source's coverage watermark advances only on proven coverage, records what it claimed, and says why when it refuses. Closes the defect that cost coverage on 2026-09-26.

**Independent Test**: record a source's watermark, run an applying pull whose download step cannot do its job, and confirm the watermark is unchanged, the source is reported as failed rather than OK, and a following routine refresh still requests the whole uncovered interval.

### Tests for User Story 1 (write first, confirm failing)

- [X] T019 [P] [US1] Failing contract tests for the universal preconditions in `tests/unit/test_advance_decision.py` — [contracts/coverage-proof.md](contracts/coverage-proof.md) §4.1, cases 9, 10, 11, 12
- [X] T020 [P] [US1] Failing contract tests for per-mode requirements in `tests/unit/test_advance_decision_modes.py` — §4.2, cases 15, 16
- [X] T021 [P] [US1] Failing contract test for the null-ingest discrimination in `tests/unit/test_advance_decision_null_ingest.py` — §4.3, cases 13 and **14 (the incident case)**
- [X] T022 [P] [US1] Failing integration test for run-start watermark semantics in `tests/integration/test_pull_state_semantics.py` — case 17
- [X] T023 [P] [US1] Failing integration test for journal-before-catalog ordering in `tests/integration/test_pull_journal_order.py` — case 18, including an interruption between the two writes leaving the journal authoritative and the watermark stale
- [X] T024 [P] [US1] Failing integration test for narrow-then-routine coverage in `tests/integration/test_pull_narrow_then_routine.py` — a narrow pull leaves the watermark, and the next routine refresh requests the full original interval
- [X] T025 [P] [US1] Failing safety test asserting the constructed argument list never contains `--auto-delete`, `--delete-after-download` or `--keep-icloud-recent-days` in any mode, in `tests/unit/test_icloud_args_safety.py` — case 22, Constitution Principle I
- [X] T026 [P] [US1] Regression test that the 7-day window overlap survives mode resolution, extending `tests/unit/test_pull_window.py` — FR-009: `window_since()` still subtracts `WINDOW_OVERLAP_DAYS` for both ROUTINE_BOUNDED and RECONCILE, and no mode path bypasses it. Existing cases in this file must keep passing unchanged.

### Implementation for User Story 1

- [X] T027 [US1] Implement `Decision` (`Advance` / `Refuse`) and `decide_advance()` in `src/archivist/coverage.py` per [contracts/coverage-proof.md](contracts/coverage-proof.md) §4 — universal preconditions in order, then per-mode requirements
- [X] T028 [US1] Implement the `EXPLICIT_SINCE` watermark comparison in `src/archivist/coverage.py` — refuse when the start date is later than the current watermark, naming the span that would be skipped
- [X] T029 [US1] Implement the null-ingest discrimination in `src/archivist/coverage.py` per §4.3 (depends on T001 — do not implement against the un-amended FR-003)
- [X] T030 [US1] Capture `run_started` before the download begins in `_pull_one` in `src/archivist/cli.py` and use it as the advance value
- [X] T031 [US1] Replace the four-clause condition at `src/archivist/cli.py:828` with a single `decide_advance()` call, writing the journal record before the `meta` update and committing after
- [X] T032 [US1] Surface the refusal reason per source in `src/archivist/cli.py` — FR-008 and FR-026; the reason string from `Decision.Refuse` is printed verbatim
- [X] T033 [US1] Write `coverage:<source>` alongside the watermark on advance in `src/archivist/cli.py`, mirroring the latest journal record

**Checkpoint**: watermarks no longer lie. Runs are still slow and still noisy, and existing holes are unrepaired — both by design at this point.

---

## Phase 4: User Story 2 — Holes get found and filled (Priority: P2)

**Goal**: a second per-source watermark plus auto-escalation, so a stale source gets a full sweep on the tool's own schedule. This is also what repairs the 2026-09-26 holes and what makes US3's bounded scan safe to ship.

**Independent Test**: set a source's reconciliation watermark older than the interval, place in the source an item whose capture date predates the coverage watermark and an item inside a known uncovered interval, run a routine refresh, and confirm the tool announces the sweep and files both.

### Tests for User Story 2 (write first, confirm failing)

- [X] T034 [P] [US2] Failing unit tests for the `is_due` predicate in `tests/unit/test_reconcile_due.py` — absent watermark is due (FR-016), fresh is not, boundary at exactly the interval
- [X] T035 [P] [US2] Failing integration tests for escalation in `tests/integration/test_reconciliation.py` — a due source sweeps unbounded, a fresh source stays bounded, `--no-reconcile` suppresses escalation while still reporting overdue
- [X] T036 [P] [US2] Failing integration tests for reconciliation watermark advance rules in `tests/integration/test_reconcile_state.py` — contract cases 19, 20, 21
- [X] T037 [P] [US2] Failing integration test that a sweep files an item whose capture date predates the coverage watermark in `tests/integration/test_reconcile_backdated.py`
- [X] T038 [P] [US2] Failing integration test that one sweeping source does not stop the others in `tests/integration/test_reconcile_isolation.py`

### Implementation for User Story 2

- [X] T039 [P] [US2] Add `reconcile_state_key()` and `is_due()` to `src/archivist/icloud.py` per [data-model.md](data-model.md) §2
- [X] T040 [P] [US2] Add `reconcile_interval_days` resolution (per-source → top-level → default 30) and its validation to `src/archivist/config.py` per [contracts/config-schema.md](contracts/config-schema.md) §1 and §3
- [X] T041 [US2] Resolve `RECONCILE` vs `ROUTINE_BOUNDED` per source in `_pull_one` in `src/archivist/cli.py`, and construct the unbounded argument list for a sweep
- [X] T042 [US2] Emit the pre-sweep announcement in `src/archivist/cli.py` — FR-014: which source, how long since last reconciliation, and that this run will take longer
- [X] T043 [US2] Advance `reconcile_state:<source>` per [contracts/coverage-proof.md](contracts/coverage-proof.md) §4.4 in `src/archivist/cli.py` — only on `RECONCILE`/`BOOTSTRAP_FULL` with an `Advance` decision and zero ingest failures
- [X] T044 [US2] Add the `--no-reconcile` flag to `pull all` in `src/archivist/cli.py` per [contracts/cli-pull.md](contracts/cli-pull.md) §1

**Checkpoint**: gaps self-heal on a cadence. A deployment now repairs the peepaw-cell and matt-public holes on its first applying run.

---

## Phase 5: User Story 3 — A refresh costs what changed (Priority: P3)

**Goal**: bound the routine scan with `--recent <scan_bound>` so enumeration stops early, with an undersized bound reporting itself instead of skipping silently.

**Independent Test**: with a source that has no new items, run a routine refresh and confirm it examines no more than the configured bound, reports the count, and finishes in bounded time; then repeat with a handful of new items and confirm all are fetched.

### Tests for User Story 3 (write first, confirm failing)

- [X] T045 [P] [US3] Failing unit tests for `scan_bound` resolution and validation in `tests/unit/test_scan_bound_config.py` — per-source override, top-level fallback, default 500, rejection of `< 1`, rejection on a non-icloud source, warning below 50
- [X] T046 [P] [US3] Failing unit test that `ROUTINE_BOUNDED` builds `--recent <scan_bound>` alongside `--skip-created-before` in `tests/unit/test_bounded_args.py`
- [X] T047 [P] [US3] Failing contract tests for the window-cleared determination in `tests/unit/test_reached_before_cutoff.py` — cases 7 and 8
- [X] T048 [P] [US3] Failing integration test that an undersized bound holds the watermark and names the setting in `tests/integration/test_scan_bound_insufficient.py`

### Implementation for User Story 3

- [X] T049 [P] [US3] Add `scan_bound` resolution and validation to `src/archivist/config.py` per [contracts/config-schema.md](contracts/config-schema.md) §1 and §3
- [X] T050 [US3] Pass `--recent <scan_bound>` for `ROUTINE_BOUNDED` runs in `src/archivist/icloud.py`
- [X] T051 [US3] Require `proof.reached_before_cutoff` for `ROUTINE_BOUNDED` in `decide_advance()` in `src/archivist/coverage.py`, with the refusal text from [contracts/coverage-proof.md](contracts/coverage-proof.md) §4.2
- [X] T052 [US3] Report the examined count and the bound per source in `src/archivist/cli.py`

**Checkpoint**: routine refreshes are fast, and a bound too small for a source's rate of change says so rather than skipping.

---

## Phase 6: User Story 4 — I can tell what the run is doing (Priority: P4)

**Goal**: a legible per-source block and a summary that distinguishes "nothing to do" from "did nothing" — the distinction whose absence let the incident pass unnoticed.

**Independent Test**: run a refresh and confirm the per-source output is a small number of summary lines with no per-item narration, that each states whether the watermark advanced, and that `--verbose` restores full detail.

### Tests for User Story 4 (write first, confirm failing)

- [X] T053 [P] [US4] Failing test that default verbosity emits no per-item skip narration and at most ten lines per source in `tests/integration/test_pull_output_quiet.py` — FR-024, SC-008
- [X] T054 [P] [US4] Failing test that `--verbose` restores raw per-item detail in `tests/integration/test_pull_output_verbose.py` — FR-025
- [X] T055 [P] [US4] Failing test for the status vocabulary in `tests/integration/test_pull_summary_status.py` — `OK` / `IDLE` / `PARTIAL` / `FAILED` / `BOOTSTRAP` per [contracts/cli-pull.md](contracts/cli-pull.md) §3.2, asserting `IDLE` and `FAILED` are distinguishable
- [X] T056 [P] [US4] Failing test for exit codes in `tests/integration/test_pull_exit_codes.py` — §4, including `PARTIAL` exiting 0

### Implementation for User Story 4

- [X] T057 [US4] Implement the per-source output block in `src/archivist/cli.py` per [contracts/cli-pull.md](contracts/cli-pull.md) §3.1 — path taken, examined/downloaded/already-present, elapsed time, ingest counts, coverage outcome
- [X] T058 [US4] Implement the status vocabulary and the summary table in `src/archivist/cli.py` per §3.2
- [X] T059 [US4] Implement the summary footer in `src/archivist/cli.py` — sources overdue for reconciliation and the suggested next command
- [X] T060 [US4] Implement the exit-code mapping in `src/archivist/cli.py` per §4

**Checkpoint**: all four stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T061 [P] Correct the `src/archivist/icloud.py` module docstring — the mirror is transient pass-through storage, not a "PERSISTENT per-source mirror" whose contents make repeat pulls incremental (FR-030; the current text predates feature 004's prune decision and is now wrong)
- [X] T062 [P] Document `scan_bound` and `reconcile_interval_days` in `config.example.yaml` with the defaults and the busiest-source guidance
- [X] T063 [P] Document the first-run reconciliation storm in `README.md` — every source escalates on the first applying run because no `reconcile_state` key exists, and `--no-reconcile` stages it (see [contracts/config-schema.md](contracts/config-schema.md) §4)
- [X] T064 [P] Add `pull-<run_id>.jsonl` to the manifest documentation in `README.md` alongside the ingest and cleanup manifests
- [ ] T065 Run the full suite in `tests/` on macOS and on the Debian host — `uv run pytest -q` — confirming no new platform-specific skips (SC-010, constitution Development Workflow). **macOS: 287 passing. Debian host not reachable from this session — unverified, do not tick on macOS alone.**
- [X] T066 Focused safety review of the diff across `src/archivist/` (chiefly `icloud.py`, `cli.py`, `coverage.py`) with the `data-safety-reviewer` agent — the change alters what the tool believes is archived, which the constitution's review gate covers even though no delete path is touched
- [X] T067 Work [quickstart.md](quickstart.md) Scenarios 1–5 end to end and record the results
- [ ] T068 **OPERATOR ACTION — not code.** Repair the 2026-09-26 holes per [quickstart.md](quickstart.md) Scenario 6: re-authenticate, then `pull icloud --source peepaw-cell --since 2026-08-19 --apply` and the same for `matt-public`, then run the verification query. Satisfies SC-004. **An implementation run must not tick this box.**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: no dependencies. T001 is a spec edit and gates T029 only.
- **Phase 2 Foundational**: depends on Phase 1 (fixtures, version constant). **Blocks every user story.**
- **Phase 3 US1**: depends on Phase 2. No dependency on US2–US4.
- **Phase 4 US2**: depends on Phase 2 and on `decide_advance()` from US1 (T027), because §4.4 gates the reconciliation watermark on the coverage decision.
- **Phase 5 US3**: depends on Phase 2 and on `decide_advance()` from US1 (T027), because T051 extends it.
- **Phase 6 US4**: depends on Phase 2; reads `Decision` outcomes from US1 for the status vocabulary. Buildable against US1 alone.
- **Phase 7 Polish**: depends on the stories being shipped. T061–T064 are documentation and can run any time after Phase 2.

### Story Dependencies — read this before parallelizing

The stories are **not** fully independent, and the spec says so deliberately:

- **US1 is a true prerequisite**, not just the highest priority. US2, US3 and
  US4 all consume `decide_advance()`.
- **US3 must not ship without US2.** A bounded recency scan structurally cannot
  see recently-added-but-old media; reconciliation is the safety net. Shipping
  US3 alone converts a slow complete tool into a fast lossy one. If only two
  stories can land, land US1 and US2.
- **US4's `IDLE` vs `FAILED` distinction is correctness-adjacent**, not
  cosmetic — it is part of how the incident went unnoticed.

### Within Each Story

Tests written and failing → data/config → decision logic → CLI wiring → output.

### Parallel Opportunities

- Phase 1: T002, T003, T004 together.
- Phase 2 tests: T005–T009 together (five separate files).
- Phase 3 tests: T019–T026 together (eight separate files).
- Phase 4 tests: T034–T038 together; implementation T039 and T040 together
  (different files), then T041–T044 serially in `cli.py`.
- Phase 5 tests: T045–T048 together; T049 parallel with them.
- Phase 6 tests: T053–T056 together.
- Phase 7: T061–T064 together.

Implementation tasks inside `src/archivist/icloud.py` (T010–T014, T050) and
`src/archivist/cli.py` (T017, T018, T030–T033, T041–T044, T052, T057–T060) are
serial within each file.

---

## Parallel Example: User Story 1

```bash
# All eight US1 test files are independent — write them together:
Task: "Universal preconditions in tests/unit/test_advance_decision.py"
Task: "Per-mode requirements in tests/unit/test_advance_decision_modes.py"
Task: "Null-ingest discrimination in tests/unit/test_advance_decision_null_ingest.py"
Task: "Run-start semantics in tests/integration/test_pull_state_semantics.py"
Task: "Journal-before-catalog ordering in tests/integration/test_pull_journal_order.py"
Task: "Narrow-then-routine coverage in tests/integration/test_pull_narrow_then_routine.py"
Task: "Argument-list safety in tests/unit/test_icloud_args_safety.py"
Task: "Window-overlap regression in tests/unit/test_pull_window.py"

# Then implementation, serially: coverage.py (T027-T029) before cli.py (T030-T033).
```

---

## Implementation Strategy

### MVP: Phases 1–3 (US1 only)

1. Phase 1 Setup — resolve T001 first, ideally via `/speckit-analyze`.
2. Phase 2 Foundational.
3. Phase 3 US1.
4. **STOP and VALIDATE**: quickstart Scenarios 2 and 3. Watermarks stop lying.
5. Shippable. Runs are still slow, still noisy, and the two existing holes are
   still open — all acceptable for an increment whose job is to stop the
   bleeding.

### Recommended first release: Phases 1–4 (US1 + US2)

US2 is what repairs the existing holes and what makes US3 safe later. This is
the smallest scope that leaves the archive *correct* rather than merely
no-longer-degrading. Note that the first applying run in this scope escalates
every source to a sweep and will take a while — that is the repair happening.

### Incremental delivery after that

1. + US3 → validate Scenario 4 → refreshes become fast.
2. + US4 → validate Scenarios 1 and 5 → runs become legible.
3. Phase 7, then T068 by hand.

### Single-operator note

This is a one-developer project, so the parallel-team strategy in the template
does not apply. The `[P]` markers are batching hints for a single session, not
staffing plans.

---

## Notes

- `[P]` = different file, no dependency on incomplete work.
- Tests are mandatory here (FR-033 + constitution), and the contract test table
  in [contracts/coverage-proof.md](contracts/coverage-proof.md) §6 is the
  authoritative checklist — every row maps to a task above.
- Confirm each test fails before implementing against it. Contract case 14 is
  the incident; if that test ever passes before T027 exists, the test is wrong.
- Commit after each task or logical group.
- No task in this feature adds, extends, or touches a deletion path.
- T068 is the operator's, not the implementation's.
