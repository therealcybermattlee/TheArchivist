# Feature Specification: The Archivist — Family Media Archival Tool (Baseline)

**Feature Branch**: `001-archivist-baseline`

**Created**: 2026-07-28

**Status**: Baseline (documents the tool as designed; portions already delivered)

**Input**: User description: "the whole Archivist tool as a baseline spec"

## Overview

The Lee Family keeps its complete photo and video history on a family-owned
network storage archive, organized by year, then by dated event folder, then by
the device that captured the media (for example: `2024 / 12312024 - New Years
Eve / GoPro3`). Media accumulates faster than it can be filed: it lives in
cloud photo libraries, on cameras and drones, on relatives' phones, and in
loose folders of old copies. The Archivist is an on-demand tool, run from the
family archivist's computer, that gathers media from all of these places,
determines when each item was captured, files it into the existing archive
structure, prevents duplicates from accumulating, and helps clean up the
duplicates and junk already present — all without ever putting the original
copies at risk.

## Clarifications

### Session 2026-07-29

- Q: What form should "review" of low-confidence-dated items take in the baseline scope? → A: An interactive review workflow: the tool presents each flagged item and can re-file it to a corrected date on approval.

### Session 2026-07-30

- Q: Does the baseline include an automated rollback capability that reverses an applied run from its journal, or is the journal a complete record used for manual recovery only? → A: Record-only — the journal is a complete, human-usable record; recovery is manual (e.g., moving files back from quarantine); no automated undo command in baseline scope.
- Q: How should ingest treat legitimate non-media files (documents, PDFs, archives, etc.) found in an ingest source folder? → A: Skip and report — not filed into the archive, but the ingest plan and run report list the non-media files skipped, so nothing disappears silently.
- Q: When a single ingest source contains multiple byte-identical copies of the same file, what should happen? → A: File exactly one copy; the other copies are reported as within-batch duplicates, mirroring how archive duplicates are skipped.

### Session 2026-07-31

- Q: May the tool ever delete files from its own drop inboxes/staging areas (feature 004's prune)? → A: Yes, as an explicit carve-out to FR-011: the tool's own inboxes and staging live inside its working directory (PLAN.md's "own scratch, when asked" allowance); the guarded prune may remove only items whose verified archived copy is confirmed present. External sources remain absolutely read-only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Take stock of the existing archive (Priority: P1)

As the family archivist, I point the tool at the existing archive so it builds
a complete inventory: every media file, its capture date (with a confidence
level), its size, its identity fingerprint, and where it sits in the folder
structure. This inventory is the foundation every other capability builds on —
duplicate detection, cleanup, and "have I already archived this?" checks.

**Why this priority**: Nothing else can work safely without knowing what is
already in the archive. Deduplication, cleanup, and ingest all consult this
inventory.

**Independent Test**: Run the inventory against the mounted archive and
confirm the reported file count, total size, and per-year breakdown match
reality; spot-check that sampled files show correct capture dates.

**Acceptance Scenarios**:

1. **Given** the archive volume is mounted, **When** the archivist runs the
   inventory scan, **Then** every media file is recorded with its location,
   size, identity fingerprint, best-guess capture date, and a confidence
   rating for that date.
2. **Given** a scan was interrupted or media was added since the last scan,
   **When** the scan runs again, **Then** already-inventoried files are not
   re-processed from scratch and the inventory reflects the current archive.
3. **Given** system junk files (indexing artifacts, hidden files) exist in the
   archive, **When** the scan runs, **Then** they are excluded from the media
   inventory.

---

### User Story 2 - Clean up duplicates and junk safely (Priority: P1)

As the family archivist, I ask the tool for a cleanup plan: exact duplicates
(keeping the best-placed copy), corrupt files masquerading as media, and known
junk. I review the plan, approve it, and the tool moves the condemned files to
a quarantine area inside the archive. After a verification pass confirms every
kept copy is present and intact, I approve a purge that permanently removes
the quarantined files.

**Why this priority**: The archive accumulated years of copy errors —
hundreds of gigabytes of exact duplicates and corrupt files. Reclaiming that
space and trusting the archive's contents is a primary goal, and it must be
impossible for cleanup to destroy the last copy of anything.

**Independent Test**: Run cleanup on the real archive; verify one copy of
every duplicate group survives, quarantined files are recoverable before
purge, and the purge refuses to run if any kept copy is missing.

**Acceptance Scenarios**:

1. **Given** groups of byte-identical files exist, **When** a cleanup plan is
   generated, **Then** exactly one copy per group is kept (preferring the
   correctly dated, better-organized location) and the rest are marked for
   quarantine.
2. **Given** a cleanup plan is approved, **When** it is applied, **Then**
   condemned files are moved (not deleted) into a quarantine area, each move
   is journaled before it happens, and every duplicate is re-verified as
   byte-identical to its kept copy immediately before being moved.
3. **Given** files sit in quarantine, **When** the archivist requests a purge,
   **Then** the tool first verifies every kept counterpart still exists, and
   refuses to delete any quarantined file whose kept copy cannot be found.
4. **Given** the archive volume disconnects mid-operation, **When** any
   cleanup or purge step runs, **Then** the tool halts without deleting or
   moving anything further, and reports the interruption.

---

### User Story 3 - Ingest loose media into the archive (Priority: P2)

As the family archivist, I point the tool at a folder of loose media (a
relative's phone dump, an old backup folder, a camera card) and name the
source (for example "Peepaw Cell"). The tool works out when each item was
captured, groups companion files that belong together (a photo and its paired
motion clip, an edit sidecar), skips anything already in the archive, shows me
the filing plan, and — on my approval — copies everything into the correct
`Year / Date / Device` folders, verifying each copy is byte-perfect before
recording it as archived. Originals are never modified or deleted.

**Why this priority**: This is the core day-to-day workflow — it turns piles
of unfiled media into archive content. It depends on the inventory (P1) for
duplicate detection.

**Independent Test**: Ingest a sample folder containing dated media, paired
companion files, and known duplicates; confirm correct folder placement,
companions kept together, duplicates skipped, and originals untouched.

**Acceptance Scenarios**:

1. **Given** a folder of media with embedded capture dates, **When** it is
   ingested for a named source, **Then** each item lands in
   `<Year>/<MMDDYYYY> - Unsorted/<Device Folder>` per its capture date, and
   the archivist can later rename the date folder with event information.
2. **Given** media whose embedded date is missing, **When** it is ingested,
   **Then** the tool falls back to dates found in file names, then to file
   timestamps, files the item by its best guess, and records the lower
   confidence so it can be reviewed later.
3. **Given** an item already exists in the archive (byte-identical), **When**
   ingest runs, **Then** the item is skipped and reported as a duplicate
   rather than filed twice.
4. **Given** an approved ingest plan, **When** copying runs, **Then** every
   copy is verified byte-perfect against its original before the item is
   recorded as archived, and a journal of the run is kept.
5. **Given** any ingest run, **When** it completes or fails, **Then** the
   source files are unchanged (read-only handling throughout).

---

### User Story 4 - Pull cloud photo libraries (Priority: P2)

As the family archivist, I connect the tool to the family's cloud photo
accounts (two Apple accounts today). After a one-time interactive sign-in
(password and two-factor code entered by me, stored only in the computer's
secure credential store), the tool can download each library — or just the
most recent items — into a persistent local mirror on the working drive, then
run the standard ingest flow to file new items into the archive. Repeat pulls
are incremental. The cloud library is never modified or deleted from.

**Why this priority**: The phones are the family's main cameras; cloud pull is
the ongoing feed of new media. It builds entirely on the ingest flow (P2).

**Independent Test**: Authenticate one account, pull a small recent window,
confirm items download to the mirror and the ingest plan files them
correctly; re-run and confirm already-pulled items are skipped.

**Acceptance Scenarios**:

1. **Given** a configured cloud account, **When** the archivist completes the
   one-time sign-in, **Then** later pulls run without prompting, and no
   password is ever stored in configuration files or logs.
2. **Given** a signed-in account, **When** a pull requests the N most recent
   items, **Then** those items (photos at original quality, including paired
   motion clips) arrive in the local mirror and are then filed via the
   standard ingest flow.
3. **Given** a prior pull exists, **When** a pull runs again, **Then**
   already-downloaded items are not downloaded again.
4. **Given** any pull, **When** it runs, **Then** nothing is deleted or
   altered in the cloud account.
5. **Given** an expired sign-in session, **When** a pull is attempted,
   **Then** the tool stops and tells the archivist to re-run the sign-in step.

---

### User Story 5 - Guard rails against unmounted storage (Priority: P1)

As the family archivist, I need certainty that the tool cannot mistake a
disconnected network drive for an empty archive. Both the archive volume and
the local working volume carry identity markers; every state-changing command
first verifies the correct volumes are mounted, writable, and carry the
expected markers, and refuses to run otherwise.

**Why this priority**: The archive lives on a network share that can drop.
Without this guard, a disconnected share could cause writes to the wrong disk
or make verification falsely report the archive empty — the highest-risk
failure mode in the whole system.

**Independent Test**: Unmount the archive volume and attempt each
state-changing command; all must refuse with a clear message and touch
nothing. (This scenario occurred twice in real use; the guard held both
times.)

**Acceptance Scenarios**:

1. **Given** the archive or working volume is not mounted (or lacks its
   identity marker), **When** any command that writes, moves, or deletes is
   invoked, **Then** the command refuses to run and explains which volume
   check failed.
2. **Given** a volume disconnects mid-run, **When** the tool next touches
   that volume, **Then** it halts the run rather than continuing against a
   missing or wrong target.

---

### Edge Cases

- Media with no recoverable date at all: filed by file-timestamp best guess,
  flagged at lowest confidence for the interactive review workflow (FR-027) —
  never left behind.
- Companion files (photo + motion clip, image + edit sidecar, video +
  telemetry track): filed together in the same destination folder, dated by
  the best-dated member of the group.
- Two different files whose names collide at the same destination: the
  incoming file receives a distinguishing suffix; nothing is ever overwritten.
- Files with media extensions but non-media contents (e.g., an error page
  saved as a video): detected as suspect, reported for cleanup, never filed
  as media.
- Legitimate non-media files in an ingest source (documents, PDFs, archives):
  never filed, but listed in the ingest plan and run report as skipped
  non-media — they are not silently ignored.
- Video timestamps recorded in universal time: converted to the family's home
  timezone before choosing a date folder, so late-night media files under the
  correct local day.
- Dates that are implausible (before 1990 or in the future): rejected as
  evidence; the resolver falls through to the next source.
- Interrupted cleanup or ingest runs: journals are written incrementally
  before each destructive step, so a partial run is fully accounted for and
  manually recoverable from the journal record.
- A quarantined duplicate whose kept copy has gone missing: purge refuses to
  delete it — the quarantined file may be the last copy.
- Symbolic links encountered during cleanup: skipped, never followed.

## Requirements *(mandatory)*

### Functional Requirements

**Inventory & identity**

- **FR-001**: The system MUST inventory every media file in the archive with
  its location, size, capture date, date confidence, dimensions or duration,
  capturing device (when recoverable), and identity fingerprints.
- **FR-002**: The system MUST maintain two identity levels: a fast fingerprint
  for candidate matching at multi-terabyte scale, and a full-content
  fingerprint that MUST confirm any match before a file is treated as a
  duplicate for any destructive or skip decision.
- **FR-003**: The system MUST exclude operating-system junk and hidden files
  from the media inventory.
- **FR-004**: Repeat scans MUST be incremental — unchanged, already-inventoried
  files are not fully re-processed.

**Date resolution**

- **FR-005**: The system MUST determine capture dates from embedded metadata
  first, then from date patterns in file names (including US month-day-year
  forms), then from file timestamps, recording which source was used and a
  confidence level.
- **FR-006**: The system MUST treat video metadata timestamps as universal
  time and convert them to the configured home timezone before choosing a
  date folder; photo metadata timestamps are treated as local time.
- **FR-007**: The system MUST reject implausible dates (before 1990 or in the
  future) and fall through to the next evidence source.

**Archive structure & filing**

- **FR-008**: The system MUST file media into the existing archive convention:
  year folder, then `MMDDYYYY - <event>` folder, then a device folder from a
  configured source-to-device mapping; date-only folders are created as
  `MMDDYYYY - Unsorted` for later manual event naming.
- **FR-009**: The system MUST keep companion files (paired photo/motion clip,
  edit sidecars, telemetry tracks) together in the same destination folder,
  dating the group by its most reliably dated member.
- **FR-010**: The system MUST never overwrite an existing file at a
  destination; name collisions between different files receive a
  distinguishing suffix.

**Safety invariants (apply to every capability)**

- **FR-011**: The system MUST treat all sources (cloud accounts, devices, drop
  folders) as read-only: no source file is ever modified, moved, or deleted,
  and nothing is ever deleted from a cloud account. One explicit carve-out
  (added 2026-07-31 for the working-storage discipline in feature 004): files
  in the tool's OWN drop inboxes and staging areas — which live inside the
  tool's working directory — may be deleted by the dedicated, guarded prune
  command, and only when their verified archived copy is confirmed present;
  external sources (cloud accounts, device cards, any folder outside the
  tool's working directory) remain absolutely read-only.
- **FR-012**: The system MUST write only to the designated archive volume and
  the designated local working volume; replication to any secondary archive is
  outside the system and remains the owner's responsibility.
- **FR-013**: Every state-changing command MUST first verify that the archive
  and working volumes are mounted, writable, and carry their expected identity
  markers, and MUST refuse to run otherwise; mid-run disconnection MUST halt
  the run.
- **FR-014**: Every destructive or filing action MUST be preceded by a
  reviewable plan; no plan executes without explicit approval on that
  invocation.
- **FR-015**: Archive copies MUST be verified byte-perfect against their
  source before the item is recorded as archived.
- **FR-016**: Every applying run MUST journal each action incrementally,
  before the action's destructive step, so any interruption leaves a complete
  record from which the operator can recover manually; the system provides no
  automated rollback command in the baseline.

**Cleanup**

- **FR-017**: The cleanup planner MUST identify exact-duplicate groups and
  keep exactly one copy per group, preferring the copy in the best location
  (correctly dated folder, organized placement); the kept copy MUST be immune
  from condemnation by any other group in the same plan.
- **FR-018**: The cleanup planner MUST identify corrupt files (media
  extension, non-media content) and configured junk file types.
- **FR-019**: Applying cleanup MUST move condemned files to a quarantine area
  within the archive (never immediate deletion), re-confirming full-content
  identity for each duplicate immediately before its move.
- **FR-020**: Purging quarantine MUST verify every kept counterpart exists
  first, MUST refuse to delete any quarantined file whose kept copy is
  missing, and MUST only ever delete inside the quarantine area.

**Ingest pathways**

- **FR-021**: The system MUST support ingest from local folders (drops and
  device cards) for any configured named source, mapping it to its device
  folder. Legitimate non-media files found in a source (documents, archives,
  and other non-junk file types) are never filed, but the ingest plan and run
  report MUST list them as skipped non-media so nothing disappears silently.
- **FR-022**: The system MUST skip items whose full-content identity already
  exists in the archive, reporting them as duplicates rather than filing
  twice. When a single ingest source contains multiple byte-identical copies
  of the same content, exactly one copy is filed and the rest are reported as
  within-batch duplicates.
- **FR-023**: The system MUST support pulling configured cloud photo accounts
  into a persistent per-account local mirror: one-time interactive sign-in
  (credentials held only in the computer's secure credential store, never in
  configuration or logs), incremental repeat pulls, original-quality media
  including paired motion clips, and optional recent-window or since-date
  limits.
- **FR-024**: When a cloud session has expired, the pull MUST stop with a
  clear instruction to re-run sign-in, rather than failing partway through
  ambiguously.

**Operation & visibility**

- **FR-025**: The system MUST run on demand from the archivist's computer and
  provide a status view covering volume health, inventory counts, and
  last-run outcomes.
- **FR-026**: The system MUST report each run's outcome: counts filed,
  skipped as duplicates, skipped as non-media, quarantined, errored, and
  flagged for review.
- **FR-027**: The system MUST provide an interactive review workflow that
  presents each item filed on lower-confidence date evidence, one at a time
  with its evidence (guessed date, date source, current location), and — on
  the archivist's approval of a corrected date — re-files the item (and its
  companion group together) into the corrected date folder and clears its
  review flag. Re-filing follows the same safety invariants as all filing:
  reviewable before applied, no overwrites, journaled, and the inventory
  updated to the new location.

### Key Entities

- **Media Item**: One photo or video file; carries location, size, identity
  fingerprints, capture date + source + confidence, dimensions/duration,
  capturing device, and archive status.
- **Asset Group**: Companion files that must travel together (photo + motion
  clip, image + sidecar, video + telemetry); has a primary member and a
  group date.
- **Source**: A configured origin of media (cloud account, device, drop
  folder, takeout export) mapped to one archive device folder; cloud sources
  carry an account identity.
- **Archive Location**: A `Year / Dated-Event / Device` destination folder in
  the archive volume.
- **Cleanup Plan / Ingest Plan**: A reviewable list of intended actions
  (quarantine moves, purges, or filing copies) that only executes on
  approval.
- **Run Journal**: The incremental record of an applied plan — every action,
  written before its destructive step; the basis for verification and manual
  recovery (no automated rollback).
- **Quarantine**: A holding area inside the archive where condemned files
  wait, recoverable, between cleanup and verified purge.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero source files are modified, moved, or deleted by any
  operation, across all sources and all runs — verifiable by comparing source
  trees before and after.
- **SC-002**: Zero archived items are recorded without a byte-perfect
  verification, and zero destination files are ever overwritten.
- **SC-003**: Cleanup never removes the last copy of any file: after any
  purge, 100% of kept counterparts remain present and intact (real-world
  baseline: 256/256 kept copies verified across a ~270 GB cleanup).
- **SC-004**: A full inventory scan of the existing multi-terabyte archive
  (≈5,500 files, ≈3 TB) completes in under one hour on the archivist's
  setup; repeat scans complete in minutes.
- **SC-005**: At least 95% of media with embedded metadata is filed under the
  correct local calendar date; items filed on lower-confidence evidence are
  all flagged for review.
- **SC-006**: Re-running any ingest or pull immediately after a successful
  run files zero new items (100% duplicate detection on identical content).
- **SC-007**: With storage volumes unmounted, 100% of state-changing commands
  refuse to run and touch nothing.
- **SC-008**: The archivist can go from "folder of loose media" to "reviewed
  plan applied and verified" in a single sitting of under 15 minutes for a
  typical (few-hundred-item) drop.

## Assumptions

- One operator (the family archivist) runs the tool on demand from one
  computer; no multi-user or scheduled/background operation is required.
- The archive volume and the local working volume are network/external mounts
  provided and mounted by the operator before running.
- The family's home timezone (US Eastern) is the reference for all date
  folder decisions.
- Event naming is manual and happens after filing; the tool files by date
  only (`Unsorted`) and never renames existing event folders.
- Replication of the archive to a second storage system is handled by the
  operator outside this tool and is out of scope.
- Google cloud libraries are handled via manually requested export bundles
  (the direct-download route was discontinued by the provider); the export
  ingest pathway is planned but not yet part of the delivered baseline.
- Cloud sign-in requires the operator present (password + two-factor); the
  tool never handles credentials beyond handing them to the computer's secure
  credential store.
- Perceptual (near-duplicate) matching is captured in the inventory for
  future review tooling but automated near-duplicate cleanup is out of scope
  for the baseline; only byte-identical duplicates are auto-planned.
