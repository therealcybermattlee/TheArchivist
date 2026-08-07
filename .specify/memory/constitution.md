<!--
Sync Impact Report
==================
Version change: (unratified template) → 1.0.0
Modified principles: n/a (initial ratification — all six principles new)
Added sections:
  - Core Principles I–VI
  - Scope & Boundaries
  - Development Workflow & Quality Gates
  - Governance
Removed sections: template placeholder comments
Templates requiring updates:
  - ✅ .specify/templates/plan-template.md — "Constitution Check" gate already
    present; future plans fill it from these principles instead of the
    baseline-invariants fallback used by features 001–004.
  - ✅ .specify/templates/spec-template.md — no changes required (principles
    impose no new mandatory spec sections).
  - ✅ .specify/templates/tasks-template.md — no changes required.
  - ✅ No .specify/templates/commands/ directory exists in this setup.
Follow-up TODOs: none.
Source: codifies the safety model in PLAN.md ("The Data-Flow Invariant") and
the de-facto gates applied in specs/001–004, including the 2026-07-31
FR-011 drop-inbox carve-out that motivated ratification.
-->

# The Archivist Constitution

## Core Principles

### I. Source Data Is Sacred (NON-NEGOTIABLE)

External sources — cloud accounts, device cards, and any folder outside the
tool's own working directory — are read-only, always. No code path may
modify, move, or delete a source file, and nothing is ever deleted from a
cloud account. All media flows one direction: source → (copy) → working
storage → (copy + verify) → archive.

The single carve-out (amended into baseline FR-011, 2026-07-31): files
inside the tool's OWN working directory (drop inboxes, staging, mirrors)
may be deleted only by a dedicated, guarded prune command, and only when a
byte-verified archived copy is confirmed present at that moment. This is
the "own scratch, when asked" allowance — it never extends to anything
outside the working directory.

Rationale: the family's originals are irreplaceable; every other principle
exists in service of this one.

### II. Plan Before Apply

Every command that writes, moves, or deletes runs as a dry-run by default,
producing a reviewable plan. Execution requires an explicit `--apply` on
that same invocation; approval never carries across invocations. No
destructive or filing action may exist without a plan-first mode.

Rationale: a human decision point in front of every mutation is what makes
a one-operator tool safe to run at 2 a.m.

### III. Verify Before Record

Archive copies MUST be verified byte-perfect (full content hash) against
their source before the catalog records them as archived. Destinations are
never overwritten: name collisions with different content receive
deterministic hash suffixes; collisions with byte-identical content are
duplicates and are skipped, never re-filed. Duplicate decisions
(skip/condemn) MUST be confirmed by full-content hash — a fast fingerprint
alone is never sufficient for a destructive or skip decision.

Rationale: "it's archived" must mean "the bytes are provably there."

### IV. Journal Before Destruction; the Catalog Is Derived

Every applying run journals each action to an append-only manifest BEFORE
the action's destructive step, so any interruption leaves a complete,
recoverable record. The SQLite catalog is a derived index — files plus
manifests are authoritative, and the entire catalog MUST remain rebuildable
by re-scanning. Recovery is manual from journals (no automated rollback is
promised).

Rationale: the ledger must survive the database, the network, and the run
that's writing it.

### V. Guarded Volumes

Every state-changing command MUST first verify that both the archive and
working volumes are mounted, writable, and carry their expected identity
sentinels — and MUST refuse to run otherwise, naming the failed check.
Mid-run volume loss halts the run rather than continuing against a missing
or wrong target. Writes are confined to the archive and designated working
volumes; the TrueNAS archive is the sole permanent home of media.

Rationale: an unmounted share leaving an empty, writable mount point is
the highest-risk failure mode this system faces; it has already occurred
in real use and the guard held.

### VI. Never Delete the Last Copy

Deletion is a two-phase ceremony: condemned files move to quarantine
(reversible), and purging quarantine MUST verify every kept counterpart
exists and refuse any file whose kept copy is missing. The tool only ever
deletes inside its quarantine area and its own working scratch (per
Principle I's carve-out). Cleanup keeper selection MUST immunize survivors
— a kept copy can never be condemned by another group in the same plan.

Rationale: reclaiming space is worthless if it can cost the only copy of a
memory; 445 files and 270 GB were reclaimed under this ceremony with
256/256 kept copies verified intact.

## Scope & Boundaries

- One operator (the family archivist), on-demand invocation, one applying
  host at a time. Scheduled/unattended operation requires its own future
  feature and constitutional review.
- Family data stays local: media, the catalog, and location data live only
  on family-owned hardware and in exports the archivist explicitly
  creates. Online services may be used for display enrichment (e.g., map
  tiles) only where a spec records that decision.
- Replication of the archive to secondary storage is the operator's
  responsibility, outside the tool.
- Curation (event naming) is manual and downstream; the tool files by date
  and never renames existing archive folders.

## Development Workflow & Quality Gates

- Features follow the spec-kit flow: specify → clarify → plan → tasks →
  analyze → implement. Plans MUST evaluate the Constitution Check gate
  against these principles before Phase 0 and after Phase 1.
- Safety invariants are proven by automated tests, not asserted: guard
  refusals, verify-before-record, journal-first ordering, and every
  refusal path of any deletion-capable command MUST have tests. Tests run
  against disposable fixture volumes and never touch real archive mounts.
- Any change to ingest/copy/delete/path logic gets focused safety review
  before an `--apply`-capable version is used on real data.
- Supported hosts (macOS, Debian-family Linux) MUST behave identically;
  the full suite passes on each with no undeclared platform skips.

## Governance

- This constitution supersedes ad-hoc practice. Where a feature spec
  conflicts with a principle, the feature MUST NOT proceed to
  implementation until either the feature yields or this constitution is
  explicitly amended — never by silent reinterpretation. (Precedent: the
  2026-07-31 drop-inbox carve-out was adopted by explicit amendment of
  baseline FR-011 before feature 004 could proceed.)
- Amendments: recorded here with a dated rationale, propagated to affected
  specs/templates, and versioned semantically — MAJOR for principle
  removals/redefinitions, MINOR for new principles or materially expanded
  guidance, PATCH for clarifications.
- Compliance review: `/speckit-plan`'s Constitution Check gate and
  `/speckit-analyze` (where principle conflicts are CRITICAL findings)
  are the enforcement points; `data-safety-reviewer`-style review applies
  to any new deletion path.

**Version**: 1.0.0 | **Ratified**: 2026-07-31 | **Last Amended**: 2026-07-31
