# Implementation Plan: Bounded, Honest iCloud Pulls

**Branch**: `005-bounded-icloud-pull` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-bounded-icloud-pull/spec.md`

## Summary

Stop inferring coverage and start proving it, then make the proven path cheap.

One change carries most of the feature: the iCloud download step currently
inherits the terminal and is judged by its exit status. Instead the tool
**captures** the downloader's output at debug verbosity, parses it into a
`CoverageProof`, and prints its own summary. That single shift supplies
everything the spec asks for — the positive completion signal that FR-002 needs
to replace exit-status inference, the "did the bounded scan clear its window"
determination FR-022 needs, the counts FR-026 needs for a legible summary, and
the silence FR-024 needs (the per-item narration is consumed, not displayed).

On top of that proof, three strands: **(1) watermark integrity** — a single
decision function that maps run mode plus coverage proof to advance/refuse,
replacing the four-clause boolean at `cli.py:828`, with the claimed interval
journaled on every advance; **(2) reconciliation** — a second per-source
watermark and an auto-escalation check that turns one routine refresh a month
into a full sweep, which is also what repairs the two holes the 2026-09-26
incident left; **(3) bounded routine scans** — `--recent N` (confirmed in
research to truncate the iterator via `itertools.islice`, not merely filter)
alongside the existing date filter, with an undersized bound self-reporting
rather than silently skipping.

Nothing in the ingest, dedupe, dating, placement, verification, quarantine or
prune paths is touched.

## Technical Context

**Language/Version**: Python 3.12+ (unchanged), `uv`-managed CPython

**Primary Dependencies**: unchanged — `typer`, `pyyaml`, `pillow`,
`pillow-heif`, `keyring`, `tzdata`; external `icloudpd` (v1.32.3 observed),
`exiftool`, `ffprobe`. No new packages.

**Storage**: unchanged layouts. Catalog `meta` table gains
`reconcile_state:<source>` and `coverage:<source>` keys alongside the existing
`pull_state:<source>`. New append-only journal `logs/pull-<run_id>.jsonl`
carries the authoritative coverage records.

**Testing**: `pytest` (91 existing tests, all green at plan time). New coverage
is unit-level against a fake downloader-output stream plus integration-level
against fixture volumes — no test invokes a real iCloud account.

**Target Platform**: macOS and Debian-family Linux, identical behaviour
(constitution, Development Workflow)

**Project Type**: single-project CLI

**Performance Goals**: routine refresh across all four configured sources under
two minutes with no new media (SC-005); per-source enumeration bounded at the
configured scan bound and independent of library size (SC-006, SC-007)

**Constraints**: the downloader's log strings are not a stable API — version
must be asserted and parsing must fail closed (research R2). Dry-run remains
the default. A `pull` dry-run still performs downloads; that pre-existing
behaviour is out of scope and unchanged.

**Scale/Scope**: 4 iCloud sources, ~100k catalogued assets, largest source
~40k. Touches `icloud.py` (substantially), `cli.py` (`_pull_one`, `pull_all`,
`pull_icloud`, `_run_ingest` return contract), `config.py` (two new settings),
`catalog.py` (unchanged schema, new `meta` keys only).

## Constitution Check

*GATE: evaluated before Phase 0 research and re-evaluated after Phase 1 design.*

| Principle | Assessment | Verdict |
|---|---|---|
| **I. Source Data Is Sacred** | No new write path to any source. `--auto-delete`, `--delete-after-download` and `--keep-icloud-recent-days` are never passed, and the plan adds an explicit test asserting the constructed argument list contains none of them. Mirrors remain the tool's own working scratch under the existing carve-out. | PASS |
| **II. Plan Before Apply** | Dry-run stays the default on every touched command. Watermark and coverage-record writes are gated behind `--apply` exactly as the existing state write is. The feature *removes* a class of unrequested state mutation rather than adding one. | PASS |
| **III. Verify Before Record** | Untouched — no change to hashing, collision handling, or the verify-before-catalog sequence. The feature adds a second, independent verification at a different layer: prove the download covered its window before recording that claim. Consistent in spirit. | PASS |
| **IV. Journal Before Destruction; Catalog Is Derived** | Coverage records are journaled to `logs/pull-<run_id>.jsonl` **before** the `meta` write, matching the required ordering. Watermarks remain operational state in `meta` (precedent: feature 004) and are not media-derived; audit history lives in the journal, so the catalog stays a derived index. See research R5. | PASS |
| **V. Guarded Volumes** | `_require(cfg)` mount/sentinel checks unchanged and still run before any state-changing work. A reconciliation sweep is subject to the same gate. | PASS |
| **VI. Never Delete the Last Copy** | No deletion path touched. `prune-staging`, `cleanup` and `purge` are unmodified. FR-029 explicitly preserves mirror prunability rather than expanding what may be deleted. | PASS |
| **Scope & Boundaries** | Single operator, on-demand, one applying host. Auto-escalating reconciliation runs *within* an operator-invoked refresh — it is not scheduled or unattended operation, so it does not cross the boundary that would require constitutional review. Called out explicitly because "automatic" and "unattended" are easy to conflate. | PASS |
| **Quality Gates** | Safety invariants proven by test, not asserted: FR-033 enumerates the required cases and Phase 1 fixes them as contract tests. Focused safety review applies — `data-safety-reviewer` is warranted here because the change alters what the tool believes is archived, even though it adds no delete path. | PASS |

**Result**: no violations. Complexity Tracking omitted.

## Project Structure

### Documentation (this feature)

```text
specs/005-bounded-icloud-pull/
├── plan.md              # This file
├── research.md          # Phase 0 output — R1..R7
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── cli-pull.md          # command surface + exit codes + summary format
│   ├── coverage-proof.md    # downloader output -> proof; advance decision table
│   └── config-schema.md     # new per-source settings
├── checklists/
│   └── requirements.md  # spec quality checklist (complete)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/archivist/
├── icloud.py        # HEAVY CHANGE: capture+parse the downloader stream;
│                    #   CoverageProof; window/mode construction; version assert
├── cli.py           # CHANGE: _pull_one advance decision -> single function;
│                    #   reconciliation escalation in pull_all; summary rework;
│                    #   _run_ingest return contract (distinguish "no files"
│                    #   from "not run")
├── config.py        # CHANGE: scan_bound + reconcile_interval_days settings
├── catalog.py       # NO SCHEMA CHANGE: new meta keys only
├── coverage.py      # NEW: coverage record dataclass + journal writer
└── (ingest, dedupe, staging, scanner, dates, hashing, ... untouched)

tests/
├── fixtures/icloudpd_streams/       # NEW: recorded + synthesized output streams
├── unit/                            # NEW: coverage_proof, coverage_proof_failclosed,
│                                    #   session_preflight, pull_mode, coverage_journal,
│                                    #   advance_decision{,_modes,_null_ingest},
│                                    #   icloud_args_safety, scan_bound_config,
│                                    #   reached_before_cutoff, bounded_args, reconcile_due
│   └── test_pull_window.py          # EXTEND: FR-009 overlap regression
└── integration/
    ├── _pullhelp.py                 # NEW: shared CoverageProof mock builders
    ├── test_pull_state.py           # REWRITTEN (see note)
    ├── test_pull_all.py             # REWRITTEN (see note)
    └── ...                          # NEW: reconciliation, reconcile_{backdated,isolation},
                                     #   pull_{journal_order,narrow_then_routine,
                                     #   output_quiet,output_verbose,summary_status,
                                     #   exit_codes}, scan_bound_insufficient,
                                     #   prune_staging_mirrors
```

**Note on the two rewritten files** (recorded because the plan first said
"extend"): their download mocks returned an exit code, which `download()` no
longer produces — and two cases in `test_pull_state.py` asserted the behaviour
this feature removes, namely a narrow `--recent N --apply` advancing the
watermark to the present. Those cases now assert the opposite. Tests that
encode a defect have to be inverted, not extended.

**Structure Decision**: single-project CLI layout, unchanged. One new module
(`coverage.py`) keeps the journal/record concern out of `icloud.py`, which is
already gaining the parsing responsibility. Everything else is modification in
place.

## Phase 1 Design Notes

The three artifacts below carry the detail; the decisions worth stating at plan
level are:

**The advance decision becomes one auditable function.** Today the condition is
inline at `cli.py:828` and combines four unrelated clauses, one of which
(`not (res is not None and res.failed)`) passes on a null ingest result. It
becomes `coverage.decide_advance(mode, proof, ingest_result) -> Decision`,
returning either an advance with the interval it claims or a refusal with a
named reason — which is directly what FR-008 and FR-026 must print. The
decision table is in `contracts/coverage-proof.md` and is the feature's main
test surface.

**Run mode is explicit, not inferred from a soup of optional arguments.** A
`PullMode` enum — `ROUTINE_BOUNDED`, `RECONCILE`, `BOOTSTRAP_FULL`,
`EXPLICIT_SINCE`, `NARROW`, `INGEST_ONLY` — is resolved once from the CLI
arguments and carried through. `NARROW` (any `--recent` / `--until-found` /
`--until`) can never advance the coverage watermark, which is FR-004 enforced
structurally rather than by remembering to check.

**The watermark records run-start.** Captured before the download begins and
used on advance (FR-006), closing the smaller sibling of the same bug: items
created during a long run are currently claimed as covered.

**`_run_ingest` must stop returning a bare `None` for two different things.**
It returns `None` both for "path is not a directory" and for "no files found",
and the caller cannot distinguish either from a successful empty run. It gains
a small result type; research R6 explains why "no files" must be
proof-discriminated rather than treated as an automatic refusal, and proposes
the FR-003 amendment that makes the spec consistent with it.

**Fail closed, loudly.** If the downloader version is untested or the
completion signal is absent, the watermark does not advance and the summary
says why. A future upstream rewording therefore surfaces as refused advances,
never as silent loss.

## Phase 1 Deliverables

- [data-model.md](data-model.md) — entities, `meta` keys, journal record shape,
  state transitions for both watermarks
- [contracts/coverage-proof.md](contracts/coverage-proof.md) — downloader
  output signals, `CoverageProof` fields, and the mode × proof advance decision
  table
- [contracts/cli-pull.md](contracts/cli-pull.md) — command surface, flags,
  summary format, exit codes
- [contracts/config-schema.md](contracts/config-schema.md) — new settings,
  defaults, validation
- [quickstart.md](quickstart.md) — runnable validation scenarios, including the
  incident-repair procedure

## Post-Design Constitution Re-Check

Re-evaluated after the Phase 1 artifacts: **no violations**, and two
observations worth recording.

1. **Principle IV ordering is now explicit in the contract.** The journal write
   precedes the `meta` write, and `contracts/coverage-proof.md` states that an
   interruption between them leaves the journal authoritative and the watermark
   merely stale — which is the safe direction (a stale watermark re-covers
   ground; a premature one loses it).
2. **Principle II is strengthened, not merely preserved.** The feature removes
   an existing unrequested mutation: today an applying run can write a
   watermark asserting coverage the operator never got. Scoping that under
   "plan before apply" is a reasonable reading of the principle and is noted
   for `/speckit-analyze` rather than claimed as a new gate.

## Risks Carried Into `/speckit-tasks`

| Risk | Handling |
|---|---|
| Downloader log strings are version-coupled and not an API | Assert version at startup, warn on untested versions, fail closed on missing completion signal. Parsing is isolated in one module with fixture-driven tests so an upstream change is a one-file fix. |
| FR-003 as written would strand a genuinely quiet source | **Resolved 2026-09-26.** `/speckit-analyze` surfaced it as finding F1; FR-003 amended in spec.md to permit an advance on a null ingest result only when the proof shows a complete enumeration with zero items downloaded. |
| SC-004 (re-cover the two lost intervals) is an operator action | Tracked in `quickstart.md` as a manual procedure. Must not be marked complete by an implementation run. |
| Reconciliation sweeps are slow by design and will surprise | FR-014 announcement before the sweep, and the summary states which sources are due, so a long run is predicted rather than discovered. |
| `--recent` bounds by *added* order while the date filter bounds by *capture* time | This is the structural blind spot; reconciliation is the mitigation, and it is the reason User Story 2 is P2 rather than optional. |
