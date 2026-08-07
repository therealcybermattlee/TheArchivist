# Feature Specification: Run The Archivist on a Linux Host (Proxmox)

**Feature Branch**: `004-linux-proxmox-host`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "I want to run the archivist on a linux box on my
proxmox host. Plan for eventual portability to run in either LXC or regular
debian instance."

## Overview

The Archivist currently runs from the archivist's Mac, with the working
volume on a locally attached external drive and macOS-specific behaviors
quietly baked in (image-format conversion, credential storage, mount
conventions, filesystem case-insensitivity). This feature makes the tool a
first-class citizen on a Linux guest hosted on the family's Proxmox server —
with **full workflow parity**: scan, ingest, cleanup, purge, location
backfill, map export, cloud pulls, and every safety guard behaving
identically. Portability is a stated goal, not an accident: the same
installation and configuration must work in either a lightweight container
(LXC) or a full Debian virtual machine, so the hosting choice can change
later without reworking the tool.

The safety model does not bend for the new host: sources read-only, writes
confined to the archive and designated working storage, sentinel-guarded
mounts, dry-run by default, verified copies, journaled runs. A Linux host
that cannot uphold a guard refuses to run, exactly as the Mac does.

## Clarifications

### Session 2026-07-31

- Q: Which Proxmox hosting type should be the first-built, reference deployment? → A: Debian VM first — cleanest mount and secret-storage semantics for proving the migration; the LXC variant is validated second against the already-passing checklist.
- Q: Is the Linux guest intended to become the primary day-to-day operator host? → A: Yes — the Linux guest becomes the primary operator host for routine runs; the Mac remains for development and as fallback. State migration defaults to copying the working-volume state over (US4 copy path), with rebuild as the alternative.
- Q: How large should the guest's working volume be? → A: ~50 GB. Media's permanent home is always the TrueNAS archive; the working directory is a transient pass-through, kept small because routine operation is frequent, small incremental pulls ("run the update often") — never hundreds of gigs in flight. Staged media that has been verifiedly archived is prunable; the one-time full-library bootstrap pulls are a Mac-side exception already in progress and are not part of the Linux host's steady state.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full workflow parity on a Debian guest (Priority: P1)

As the family archivist, I provision a Debian instance on the Proxmox host,
install The Archivist, point its configuration at the archive share (from
the NAS) and a designated working volume, and run every workflow I run on
the Mac today — status, archive scan, drop ingest, cleanup/purge, location
backfill, map export — with identical behavior and identical safety
refusals.

**Why this priority**: Everything else is moot unless the tool actually
works end-to-end on Linux. This surfaces and fixes every hidden
macOS dependency.

**Independent Test**: On a fresh Debian guest, install the tool, run the
full automated test suite (green), then execute the project's validation
scenarios (guard refusals with unmounted shares, scan of a fixture archive,
ingest with verification, cleanup→quarantine→purge, location backfill, map
export with converted-format thumbnails) — all passing with no
macOS-specific tooling present.

**Acceptance Scenarios**:

1. **Given** a fresh Debian instance with the documented prerequisites,
   **When** the tool is installed and configured, **Then** every CLI command
   available on the Mac is available and functional on Linux.
2. **Given** the archive share is not mounted (or its identity sentinel is
   missing), **When** any state-changing command runs, **Then** it refuses
   exactly as on macOS — naming the failed check, touching nothing.
3. **Given** media formats that need conversion for previews (e.g., HEIC),
   **When** the map export runs on Linux, **Then** thumbnails are generated
   without any macOS-only tooling, and the export is equivalent to one
   produced on the Mac.
4. **Given** the automated test suite, **When** it runs on the Linux host,
   **Then** all tests pass without platform-specific skips beyond those
   explicitly declared.

---

### User Story 2 - Cloud pulls from the Linux host, headless (Priority: P2)

As the family archivist, I connect to the Linux guest over a remote shell
(no desktop), complete the one-time interactive cloud sign-in (password +
two-factor typed into the terminal), and run incremental iCloud pulls there
— sessions and credentials stored securely on the Linux host, never in
config files or logs.

**Why this priority**: Cloud pulls are the ongoing feed of new media; if
they only work on the Mac, the Linux host is a half-migration. Depends on
US1's baseline parity.

**Independent Test**: Over a remote shell session on the guest, authenticate
one account interactively, run a small recent-window pull, verify items
mirror + ingest with all counters (including location) correct; re-run and
confirm incremental no-op; confirm no credential material in any file the
tool writes.

**Acceptance Scenarios**:

1. **Given** a remote terminal session (no graphical desktop), **When** the
   archivist runs the one-time sign-in, **Then** password and two-factor
   entry work in that terminal and the session persists for later
   non-interactive pulls.
2. **Given** an authenticated account on the Linux host, **When** pulls run,
   **Then** behavior matches the Mac: incremental mirror, Live Photo pairs
   intact, verified ingest, location captured, nothing altered in the cloud.
3. **Given** credential storage on the Linux host, **When** configuration,
   logs, and manifests are inspected, **Then** no password or session secret
   appears in any of them.

---

### User Story 3 - Same tool, either container or VM (Priority: P2)

As the family archivist, I can stand the tool up in a lightweight container
(LXC) on Proxmox or in a full Debian VM, using the same documented setup
steps and the same configuration file — and switch between the two later
without changing the tool.

**Why this priority**: The user explicitly wants the hosting decision to
stay open. Portability constraints (no host-type assumptions, mount-agnostic
guards, documented differences) must be designed in now, not retrofitted.

**Independent Test**: Execute the same documented setup in both an LXC
container and a Debian VM; run the identical validation checklist in each;
confirm the same configuration file works in both with only mount-path
provisioning differing (and that difference living outside the tool).

**Acceptance Scenarios**:

1. **Given** the documented setup procedure, **When** followed in an LXC
   container and in a Debian VM, **Then** both reach a fully working
   installation with the same validation checklist passing in each.
2. **Given** the tool's configuration, **When** moving between container and
   VM hosting, **Then** the configuration file itself is portable — storage
   provisioning (how shares/volumes are presented) is the only thing that
   changes, and it happens outside the tool.
3. **Given** either hosting type, **When** the working volume or archive
   share is presented read-only or unwritable due to host-side permission
   mapping, **Then** the tool's guard detects it and refuses state-changing
   commands with a clear message.

---

### User Story 4 - Bring the existing state along (Priority: P3)

As the family archivist, when I switch operation to the Linux host, the
catalog, run manifests, and cloud mirrors either move with me or are
regenerated — and the tool tells me which. History is never silently lost;
the Mac setup remains usable until I choose to retire it.

**Why this priority**: Continuity of the catalog (5,000+ indexed assets,
location coverage, run history) makes the migration seamless — but because
the catalog is a rebuildable derived index by design, this story is
recoverable convenience, not correctness.

**Independent Test**: Copy the working-volume state (catalog and run
manifests — mirrors stay behind as transient staging) to the Linux host's
working volume, adjust configuration paths, and confirm status/coverage
counts match the Mac's; alternatively rebuild via a fresh archive scan and
confirm parity of counts (minus expected differences documented by the
migration guide).

**Acceptance Scenarios**:

1. **Given** the Mac's working-volume state copied to the Linux host,
   **When** the tool runs `status`, **Then** catalog totals, location
   coverage, and review-queue depth match the Mac's numbers.
2. **Given** a fresh start instead (no copied state), **When** a full
   archive scan and location backfill run on Linux, **Then** the rebuilt
   catalog reconciles with the archive contents, demonstrating the
   derived-index promise.
3. **Given** cloud accounts previously authenticated on the Mac, **When**
   operating from the Linux host, **Then** each account completes its own
   one-time sign-in there (sessions are per-host and never copied), after
   which incremental pulls skip everything already archived.

---

### Edge Cases

- Case-sensitivity: the Mac's filesystems are case-insensitive; Linux is
  case-sensitive. Two archive entries differing only in case must not
  collide, duplicate, or be missed by dedup/collision logic when the archive
  is accessed from Linux (network shares may present either behavior).
- Mount semantics differ (network share on Linux vs. macOS): the sentinel
  guard must still distinguish "share mounted" from "empty local directory
  at the mount point" — the failure mode it exists for is identical on
  Linux.
- Unprivileged container ID mapping: if host-side user/permission mapping
  makes the archive or working volume unwritable (or worse, silently maps to
  the wrong ownership), guards must detect and refuse rather than half-work.
- No graphical environment: every interactive flow (cloud sign-in
  two-factor, review workflow prompts, purge confirmations) must work in a
  plain remote terminal.
- Format conversion parity: previews/thumbnails for HEIC and similar formats
  must generate on Linux without macOS tools, with visually equivalent
  results; a format that cannot be converted degrades exactly as it does on
  the Mac (item exported without preview, never dropped).
- Credential storage on a headless host: secure secret storage must work
  without a desktop keychain UI; if the host cannot provide secure storage,
  the tool must say so plainly rather than falling back to plaintext.
- Hostname/path drift between hosts: configuration validation must catch
  paths that exist on the Mac but not on the Linux guest (e.g., `/Volumes/…`
  leftovers) with actionable messages, not mid-run surprises.
- Clock/timezone: the Linux guest must produce identical date-folder
  decisions (same home-timezone normalization) regardless of the host's
  system timezone setting.
- Concurrent operation: the Mac and Linux host must not run applying
  commands against the archive at the same time; the migration guide states
  the one-operator-one-host-at-a-time rule (consistent with the baseline's
  single-operator assumption).
- Working-area cleanup safety: staged-media pruning must refuse any item
  whose archived counterpart cannot be verified in the catalog — a staged
  file may be the only copy of not-yet-archived media, and the prune must
  treat it as untouchable.
- Working storage approaching its budget mid-pull: the pull completes or
  halts cleanly with a clear message; it never silently drops items, and
  the remedy (prune verified staging, then re-run) is stated in the
  message.

## Requirements *(mandatory)*

### Functional Requirements

**Platform parity**

- **FR-001**: Every CLI capability (status, volume init, archive scan,
  ingest, drops, cleanup, purge, location backfill, map export, cloud auth
  and pull, review when delivered) MUST function on a Debian-family Linux
  host with behavior identical to macOS, including all safety refusals.
- **FR-002**: The automated test suite MUST pass on Linux; any test that is
  genuinely platform-specific MUST be explicitly declared as such rather
  than silently skipped.
- **FR-003**: Preview/thumbnail generation for formats requiring conversion
  (HEIC and kin) MUST work on Linux without macOS-only tooling, producing
  equivalent exports; per-item conversion failure degrades identically to
  macOS (item retained without preview).
- **FR-004**: All interactive flows MUST work in a plain terminal over a
  remote shell — no graphical environment may be required for any operation.

**Safety guards on the new host**

- **FR-005**: The volume identity guard MUST work identically on Linux
  mounts: both volumes present, writable, and carrying their expected
  sentinel, with refusal on any failure — including host-side permission
  mapping that renders a volume unwritable.
- **FR-006**: All existing safety invariants (read-only sources, writes
  confined to archive + working volumes, dry-run default, verified copies,
  journal-before-destructive-step) apply unchanged on Linux.
- **FR-007**: Configuration validation MUST detect paths that do not exist
  on the current host (e.g., Mac-style mount paths left in config) and fail
  fast with an actionable message before any operation begins.
- **FR-008**: Date-folder decisions MUST be independent of the host system
  timezone — the configured home timezone governs, producing identical
  filing on both platforms for identical inputs.
- **FR-009**: Dedup, collision, and identity logic MUST behave correctly on
  case-sensitive filesystems, including archives containing names that
  differ only by case.

**Cloud & credentials**

- **FR-010**: Cloud sign-in and session persistence MUST work on the
  headless Linux host: interactive password + two-factor in the terminal,
  secrets held only in the host's secure secret storage, never in
  configuration, logs, or manifests. If secure storage is unavailable, the
  tool MUST refuse with a clear explanation rather than store secrets in
  plaintext.
- **FR-011**: Cloud sessions are per-host: each account authenticates once
  per host; pulls from the new host MUST correctly skip all
  already-archived content regardless of which host archived it.

**Portability (LXC and VM)**

- **FR-012**: The documented installation procedure MUST produce a working
  deployment in both an LXC container and a Debian virtual machine, with an
  identical validation checklist passing in each. The Debian VM is the
  reference deployment, built and validated first; the LXC variant follows
  against the same checklist.
- **FR-013**: The tool MUST make no assumptions about its hosting type: all
  host-specific storage provisioning (how the archive share and working
  volume are presented) lives outside the tool, and one configuration file
  is portable across both hosting types when mount paths match.
- **FR-014**: A migration guide MUST document: prerequisites, storage
  presentation for both hosting types, state migration (copy vs. rebuild,
  per US4), per-host cloud re-authentication, and the
  one-host-applies-at-a-time rule.

**Working-storage discipline**

- **FR-015**: The tool MUST operate within a small working-storage budget
  (≈50 GB): routine cloud pulls fetch recent increments rather than
  maintaining persistent full-library local copies, and re-pulling content
  that is already archived MUST still result in zero re-filing (catalog
  dedup as the safety net).
- **FR-016**: The tool MUST provide an explicit, guarded cleanup of staged
  working-area media, which MAY remove only items whose verified archived
  copy is confirmed present in the catalog — never anything unverified, and
  never anything outside the tool's own working area. Like all destructive
  actions: plan first, apply on approval, journaled. (Deleting from the
  tool's own drop inboxes under these rules is expressly authorized by the
  2026-07-31 carve-out to baseline FR-011; external sources remain
  read-only.)

### Key Entities

- **Linux Host (Proxmox guest)**: The Debian-family LXC container or
  virtual machine where the tool runs; interchangeable by design.
- **Working Volume (Linux)**: The designated working storage (staging,
  drops, logs, catalog, exports) with the same layout and sentinel contract
  as the Mac's working drive — budgeted at ≈50 GB because media only
  transits it: frequent small pulls in, verified archival out, staged
  copies prunable afterward. Whether it is a guest-local disk or NAS-backed
  is a provisioning choice made at planning time.
- **Archive Share (from the NAS)**: The same archive volume, presented to
  the Linux guest as a network mount with its existing identity sentinel.
- **Migrated State**: Catalog and run manifests (small) — copied to the new
  working volume or rebuilt from the archive. Cloud mirrors do NOT migrate
  (staged media is transient; pulls resume with recent windows), and cloud
  sessions are explicitly per-host.
- **Validation Checklist**: The host-agnostic acceptance runbook proving a
  deployment (either hosting type) is complete and safe.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of CLI commands available on macOS run functionally on
  the Debian guest; the automated suite passes with zero undeclared
  platform skips.
- **SC-002**: With shares unmounted or sentinels absent, 100% of
  state-changing commands refuse on Linux, touching nothing — matching the
  Mac's guard behavior check-for-check.
- **SC-003**: The identical validation checklist passes in BOTH an LXC
  container and a Debian VM deployment, with zero tool-side configuration
  differences between them beyond mount paths.
- **SC-004**: A cloud account authenticated over a remote terminal on the
  Linux host completes an incremental pull whose results match the Mac's
  behavior (verified filing, pairs intact, locations captured, re-run
  no-op); zero credential material appears in any tool-written file.
- **SC-005**: After state migration (copy path), catalog totals and location
  coverage on Linux match the Mac's numbers exactly; after a from-scratch
  rebuild (rebuild path), the catalog reconciles 100% with archive contents.
- **SC-006**: A map export produced on Linux for the same catalog subset is
  functionally equivalent to the Mac's (same items plotted, previews render,
  pins clickable).
- **SC-007**: Filing decisions for a fixture set are byte-for-byte identical
  (same target paths) on macOS and Linux, including when the guest's system
  timezone is deliberately set differently.
- **SC-008**: Steady-state working-storage usage on the Linux host stays
  under 50 GB across a month of routine pull-and-prune operation, and no
  prune ever removes an item lacking a verified archived counterpart
  (0 occurrences, checked against journals).

## Assumptions

- The Proxmox host has capacity for a modest Debian guest; the working
  volume is ≈50 GB (per Clarifications) — media is transient there, with
  TrueNAS as its only permanent home. Guest-local vs. NAS-backed working
  storage is a provisioning choice at planning time.
- The archive share is presented to the guest from the existing NAS over
  the local network; presentation specifics (protocol, mount options,
  container bind vs. VM mount) are host-side provisioning, outside the
  tool.
- Routine operation on the Linux host is frequent, small incremental pulls
  rather than persistent full-library mirrors; the one-time full-library
  bootstrap is completing on the Mac before the migration and does not
  recur.
- Debian-family stable is the reference Linux target; the container image
  and VM install use the same release.
- The Linux guest becomes the primary operator host for routine runs (per
  Clarifications); the Mac remains a valid host for development and
  fallback. Only one host runs applying commands at a time, per the
  baseline's single-operator model.
- The Immich viewing layer (003) is unaffected: it reads the archive on the
  NAS regardless of which host The Archivist runs on; the post-run rescan
  trigger must work from the Linux host too.
- Existing macOS-specific behaviors (image conversion tooling, credential
  storage) are replaced by cross-platform or per-platform equivalents
  selected during planning; the spec requires equivalence of outcomes, not
  specific tools.
- This feature covers hosting The Archivist itself; scheduled/unattended
  operation remains out of scope (on-demand, single operator), though the
  Linux host is a natural prerequisite for such a future feature.
