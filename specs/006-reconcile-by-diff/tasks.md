# Tasks: Reconciliation by Enumeration Diff

**Feature**: `006-reconcile-by-diff` | **Branch**: `006-reconcile-by-diff`
**Input**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests are included.** The constitution (Development Workflow & Quality Gates)
requires safety invariants be proven by automated tests, and this feature's
central invariant — the comparison never under-reports — is exactly such a case.

---

## Phase 1: Setup

- [x] T001 Add enumeration fixtures to `tests/fixtures/icloudpd_streams/`: `enumeration-sample.log` (already generated), plus `enumeration-truncated.log` (ends mid-line), `enumeration-auth-error.log` (valid paths then `Authentication required for Account. (421)` on stdout), and `enumeration-empty.log` (zero lines)
- [x] T002 Extend `tests/fixtures/icloudpd_streams/README.md` with provenance for the new fixtures: derived from a real captured `matt-public` listing, filenames synthetic, shape preserved per research R1–R5

---

## Phase 2: Foundational (blocks every user story)

- [x] T003 [P] Add `Listing` dataclass to `src/archivist/icloud.py` with fields `paths`, `listed_lines`, `complete`, `exit_code`, `notes` per data-model.md §1
- [x] T004 [P] Add enumeration failure regexes to `src/archivist/icloud.py` — `_RE_AUTH_REQUIRED`, `_RE_ACCOUNT_LOCKED`, `_RE_BAD_CREDENTIALS` — transcribed verbatim from captured output per contracts/enumeration.md §3, reusing the existing `_RE_MFA_REQUIRED`
- [x] T005 Add `build_enumerate_cmd()` to `src/archivist/icloud.py`, sharing `_base_cmd` and matching the download invocation exactly on `--folder-structure`, `--size`, `--live-photo-size`, `--live-photo-mov-filename-policy`, plus `--log-level error --only-print-filenames`
- [x] T006 Add `enumerate_library()` to `src/archivist/icloud.py`: gate on `session_status`, run with `stdin=DEVNULL`, stream stdout, classify each line by mirror prefix, dedupe paths, detect truncation, build a `Listing`
- [x] T007 [P] Add `recorded_source_paths()` to `src/archivist/catalog.py` returning relative `original_path` values for one mirror prefix, per contracts/gap-report.md §2
- [x] T008 [P] Add `audit_interval_days` (default 7), `repair_budget_gb` (default 5), `auto_repair` (default true) to `src/archivist/config.py` with `_positive_int`-style validation and per-source overrides following `scan_bound_for`
- [x] T009 [P] Add `audit_state_key()` to `src/archivist/icloud.py` alongside the existing `pull_state_key` / `reconcile_state_key`
- [x] T010 Create `src/archivist/audit.py` with the module docstring explaining the over-report/under-report asymmetry and why it is the whole safety contract

**Checkpoint**: enumeration and the catalog side exist; nothing consumes them yet.

---

## Phase 3: User Story 1 — Prove a source complete without downloading it (P1) 🎯 MVP

**Goal**: An audit of a complete source reports it reconciled, advances the
reconciliation watermark under `--apply`, and transfers no media.

**Independent test**: Run `archivist audit --source <key> --apply` against a
source whose archive is complete; expect `RECONCILED`, an advanced watermark, a
journal record, and an unchanged staging directory.

### Tests

- [x] T011 [P] [US1] Write `tests/unit/test_enumeration_parse.py`: sample fixture yields the expected path set; truncated fixture yields `complete=False`; auth-error fixture yields `complete=False` with the reason named; empty+clean yields `complete=True` with zero paths; untested version yields `complete=False`
- [x] T012 [P] [US1] Write `tests/unit/test_gap_never_underreports.py` implementing contracts/gap-report.md §6: a property test over random archived/unarchived splits asserting every unarchived item appears in `missing`, plus the prefix-isolation and absolute-path cases
- [x] T013 [P] [US1] Write `tests/unit/test_gap_compare.py`: relative-path keying, duplicate listed paths counted once, another source's rows cannot reduce `missing`, reverse difference never affects the verdict
- [x] T014 [P] [US1] Write `tests/unit/test_audit_verdict.py` covering the contracts/gap-report.md §5 verdict table, including every precondition failure producing `Unverified`
- [x] T015 [P] [US1] Write `tests/integration/test_audit_session_gate.py` asserting an audit against unusable credentials never reaches `subprocess.Popen` (SC-008)
- [x] T016 [P] [US1] Write `tests/integration/test_audit_unfiled_mirror.py` asserting an unfiled file in the mirror forces `Unverified` even when the difference is empty (FR-008, research R7)

### Implementation

- [x] T017 [US1] Implement `GapReport` and `compare()` in `src/archivist/audit.py` per contracts/gap-report.md §2, including month derivation and the `undated` bucket
- [x] T018 [US1] Implement `Verdict` (`Reconciled` / `Incomplete` / `Unverified`) and `decide_verdict()` in `src/archivist/audit.py` enforcing all four preconditions in contracts/gap-report.md §3
- [x] T019 [US1] Implement `mirror_has_unfiled_files()` in `src/archivist/audit.py` — the FR-008 guard comparing mirror contents against catalog records
- [x] T020 [US1] Extend `src/archivist/coverage.py` so a clean audit is a second legitimate route to a reconciliation advance, without touching `decide_advance` or any coverage path
- [x] T021 [US1] Add the `kind: "audit"` journal record shape to `src/archivist/coverage.py` and write it via the existing `append_record`, fsynced before any catalog write (Principle IV)
- [x] T022 [US1] Add the `archivist audit` command to `src/archivist/cli.py` with `--source`, `--all`, `--apply`, `--force`, `--show`, `--config`, report-only by default, routed through `_require(cfg)` (Principle V)
- [x] T023 [US1] Implement the clean-source output format and exit codes per contracts/cli-audit.md §1–§2
- [x] T024 [US1] Wire the enumeration progress reporter into the audit so a 10–20 minute listing shows activity (FR-026), reusing `_progress_reporter`
- [x] T025 [US1] Write `tests/integration/test_audit_cli.py`: report-only default writes nothing, `--apply` advances both `audit_state` and `reconcile_state`, exit codes 0/1/2, and a seeded gap is detected offline

**Checkpoint**: a source can be proven complete for free. This is the MVP and
delivers the feature's core value on its own.

---

## Phase 4: User Story 2 — See what is missing, and where (P2)

**Goal**: A non-empty difference becomes a legible report, not an alarm.

**Independent test**: Seed a catalog missing a known contiguous span; the report
names the correct count and months without any transfer.

- [x] T026 [P] [US2] Write `tests/unit/test_gap_clustering.py`: contiguous span groups into the right months, scattered gaps are summarised rather than enumerated, `by_month` + `undated` == `missing_count`
- [x] T027 [US2] Implement month clustering and the scatter summary in `src/archivist/audit.py`
- [x] T028 [US2] Implement the gap output format per contracts/cli-audit.md §1, including the mandatory `(upper bound)` qualifier on every non-zero count
- [x] T029 [US2] Persist the full missing list for inspection (FR-004) alongside the run's journal record, and name the file in the output
- [x] T030 [US2] Extend the `kind: "audit"` journal record with `months_affected` and `undated`

**Checkpoint**: gaps are actionable by a human.

---

## Phase 5: User Story 3 — Repair a gap by fetching only the gap (P3)

**Goal**: Repairs transfer the affected ranges, not the library.

**Independent test**: Seed a known gap, repair, confirm the fetch is bounded to
the affected months and the items are filed.

- [x] T031 [P] [US3] Write `tests/unit/test_repair_plan.py`: contiguous months collapse into one range, the scatter cutoff of 8 months trips `too_scattered`, `expected_items` and `expected_missing` are both reported
- [x] T032 [P] [US3] Write `tests/unit/test_audit_budget.py`: within budget repairs, over budget reports, and — critically — a `None` estimate is treated as over budget (FR-030)
- [x] T033 [US3] Implement `RepairPlan` and `plan_repair()` in `src/archivist/audit.py`, estimating from the source's median archived `file_size` per research R8
- [x] T034 [US3] Add a median-file-size query for one source to `src/archivist/catalog.py`
- [x] T035 [US3] Implement `BudgetDecision` and `decide_budget()` in `src/archivist/audit.py`
- [x] T036 [US3] Add `--repair` to `archivist audit`, executing each range through the existing pull path as `EXPLICIT_SINCE` with both bounds, never introducing a new fetch path
- [x] T037 [US3] Re-audit after a repair and advance `reconcile_state` only when nothing remains missing (FR-018)
- [x] T038 [US3] Report rather than sweep when `too_scattered` (FR-019), naming the full-sweep command without running it
- [x] T039 [US3] Add the `kind: "audit_repair"` journal record per data-model.md §2
- [x] T040 [US3] Write `tests/integration/test_audit_repair.py`: bounded ranges are requested, a residual gap withholds the watermark, and a scattered gap refuses to sweep

**Checkpoint**: saved bandwidth is realized.

---

## Phase 6: User Story 4 — Keep every source honest without being asked (P4)

**Goal**: `pull all` audits each source on a 7-day interval and repairs within
budget, with every branch bounded.

**Independent test**: Run the routine refresh against a source with a seeded gap
and confirm the summary reports it without a separate command.

- [x] T041 [P] [US4] Write `tests/integration/test_pull_all_audit.py`: a source inside the interval is not audited, one outside it is, `--no-audit` suppresses, `--audit` forces
- [x] T042 [P] [US4] Write `tests/integration/test_pull_all_autorepair.py`: within-budget gaps repair automatically, over-budget gaps report, `auto_repair: false` reduces to report-only
- [x] T043 [US4] Add `is_audit_due()` to `src/archivist/audit.py` mirroring the existing `is_reconcile_due`
- [x] T044 [US4] Integrate the audit into `_pull_one` in `src/archivist/cli.py` after pull and ingest, per contracts/cli-audit.md §3
- [x] T045 [US4] Add `--no-audit` and `--audit` to both `pull all` and `pull icloud`
- [x] T046 [US4] Add the `GAP` and `UNVERIF` summary statuses to `_STATUS_STYLE` and the summary renderer, keeping them distinct from `FAILED`
- [x] T047 [US4] Add the reconciliation clause to each summary line per contracts/cli-audit.md §3 (FR-021b)
- [x] T048 [US4] Implement advice ranking per contracts/cli-audit.md §4, fixing the observed defect where sweep advice outranked three sources needing re-authentication (FR-025)
- [x] T049 [US4] Suppress the "sweep overdue" nag for any source reconciled by a clean audit (contracts/cli-audit.md §5)

**Checkpoint**: every branch of the routine refresh is bounded.

---

## Phase 7: Polish & Cross-Cutting

- [x] T050 [P] Extend `tests/unit/test_icloud_args_safety.py` so the enumeration command is covered by the Principle I assertion that no iCloud-mutating flag can ever be constructed
- [x] T051 [P] Write `tests/unit/test_audit_config.py`: defaults, per-source overrides, rejection of non-positive values and non-boolean `auto_repair`
- [x] T052 [P] Document `audit_interval_days`, `repair_budget_gb`, and `auto_repair` in `config.example.yaml` with the reasoning behind each default
- [x] T053 [P] Document the `audit` command and the audit-vs-sweep distinction in `README.md`
- [x] T054 Update `config.yaml` with the new settings so the live deployment picks up the defaults explicitly rather than implicitly
- [x] T055 Run the full suite and confirm no regression against the 345-test baseline
- [ ] T056 Validate against a live source per [quickstart.md](./quickstart.md) §4, including the `du` before/after check proving zero media transfer (SC-001)

---

## Dependencies

```
Phase 1 (Setup)
  └─> Phase 2 (Foundational) ─── blocks everything below
        └─> Phase 3 (US1, P1) ── MVP, independently shippable
              ├─> Phase 4 (US2, P2) ── needs GapReport from US1
              │     └─> Phase 5 (US3, P3) ── needs clustering from US2
              │           └─> Phase 6 (US4, P4) ── needs repair from US3
              └─> Phase 7 (Polish) ── T050/T051 can start once Phase 2 lands
```

US2 depends on US1's `GapReport`; US3 depends on US2's clustering; US4 depends
on US3's budgeted repair. The chain is real rather than incidental — each story
consumes the previous one's output — so the stories are sequential, though each
is independently testable and shippable at its checkpoint.

## Parallel opportunities

- **Phase 2**: T003, T004, T007, T008, T009 touch different files — all parallel
- **Phase 3 tests**: T011–T016 are six independent files — all parallel
- **Phase 7**: T050–T053 are independent

## Implementation strategy

**Ship Phase 3 first and stop.** US1 alone converts reconciliation from a 246 GB
unconditional sweep into a free question, which is the entire economic argument
for the feature. US2–US4 improve what happens when the answer is "something is
missing" — valuable, but the archive is already better off the moment a clean
source can be proven clean for nothing.

Write T012 (`test_gap_never_underreports.py`) **before** T017. It is the one
test whose failure means data loss rather than inconvenience, and writing it
first keeps the comparison honest while it is being designed.
