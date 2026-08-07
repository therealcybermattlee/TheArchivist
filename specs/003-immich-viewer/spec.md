# Feature Specification: Immich Viewing Layer for the Family Archive

**Feature Branch**: `003-immich-viewer`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Deploy Immich on the family TrueNAS as the
viewing and navigation layer for the archive: a read-only external library
pointed at the existing archive so the family can browse the whole library by
timeline, map, search, and faces — while The Archivist remains the only thing
that ever writes to the archive."

## Overview

The family archive is complete, deduplicated, dated, and located — but the
only way to experience it is browsing raw folders on a network share. This
feature deploys Immich (the family's chosen self-hosted photo platform) on
the family's own NAS as a pure **viewing and navigation layer**: it watches
the existing archive read-only, indexes everything in place, and gives every
family member a polished way to browse the whole library by timeline, explore
it on a map (realizing the goal behind the location catalog), search by
content, and find people by face — from their own phones and computers, on
the family's own hardware.

The system-of-record boundary is absolute and central to this feature: The
Archivist remains the **only** writer to the archive. The viewing layer can
never modify, move, or delete an archived file, no matter what a user does in
its interface. Media enters the archive exclusively through The Archivist's
verified pipeline; the viewer simply notices and displays it.

## Clarifications

### Session 2026-07-31

- Q: What is the family TrueNAS box running and what hardware does it have? → A: TrueNAS Community Edition 26.0.0-BETA.2 (Linux, app-capable) on an Intel i3-1215U (Quick Sync available) with 7.5 GiB usable RAM (~3.2 GiB free); pool "cyberfarm", 38 TiB usable at 33.7% — the same box that serves the archive share, so the viewer reads the archive dataset locally. RAM is the binding constraint: content-analysis features start disabled and are enabled only after headroom is validated (a RAM upgrade is the natural enabler). The official Immich app (v3.0.3, community train) is available in the box's TrueNAS Apps catalog — deployment uses the native catalog, not a custom container.
- Q: Should The Archivist automatically trigger a viewer rescan after each applying run? → A: Yes — auto-trigger: The Archivist calls the viewer's rescan interface after every successful applying run (ingest, pull, cleanup, purge), with the daily schedule as backstop; a failed trigger degrades gracefully to the schedule and never fails the archival run itself.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Browse the whole archive by timeline (Priority: P1)

As a family member, I open the family photo app and scroll the entire
library — every archived photo and video, newest to oldest — with fast
thumbnails and full-quality viewing, organized by the capture dates The
Archivist resolved. The archive files themselves are untouched: same bytes,
same folders, same names.

**Why this priority**: This is the core payoff — a decade of curated archive
becomes browsable by the whole family. Every other capability (map, search,
faces) builds on this initial read-only index.

**Independent Test**: Deploy the viewer, point it read-only at the archive,
let the first full index complete; verify the item count matches the
archive's inventory (minus deliberate exclusions), spot-check that photos
open at full quality, and hash-compare a sample of archive files before and
after to prove zero modification.

**Acceptance Scenarios**:

1. **Given** the viewer is deployed and its read-only library points at the
   archive, **When** the first full index completes, **Then** the complete
   archive (photos and videos) is browsable as a date-ordered timeline.
2. **Given** any amount of browsing, viewing, and interacting with the
   viewer, **When** archive files are compared before and after, **Then**
   they are byte-identical — no file modified, moved, renamed, or deleted.
3. **Given** the tool's quarantine/housekeeping areas exist inside the
   archive volume, **When** the library is indexed, **Then** those areas are
   excluded from what the family sees.
4. **Given** a family member attempts to delete or edit an archived item in
   the viewer's interface, **When** the action is attempted, **Then** the
   archived file is not deleted or altered on disk.

---

### User Story 2 - Every family member gets their own access (Priority: P2)

As the family archivist, I create an account for each family member. Each
person signs in from their own phone or computer on the home network and
browses the same shared library, with the archivist holding the only
administrative account.

**Why this priority**: The library's value multiplies when Kat, the kids,
and grandparents can each browse it themselves — but it requires the P1
index to exist first.

**Independent Test**: Create accounts for at least two non-admin family
members; each signs in from their own device, browses the timeline, and
cannot access administrative settings.

**Acceptance Scenarios**:

1. **Given** the viewer is running, **When** the archivist creates a family
   member's account, **Then** that person can sign in from their own device
   on the home network and browse the full shared library.
2. **Given** a non-admin family account, **When** that user explores the
   interface, **Then** administrative functions (library configuration, user
   management, deletion of library content) are unavailable to them.
3. **Given** the household's devices (phones, tablets, computers), **When**
   family members browse simultaneously, **Then** each session works
   independently without interfering with the others.

---

### User Story 3 - Explore the library on a map (Priority: P2)

As a family member, I open the map view and see the family's history plotted
across the country — clusters over home, vacation trails across Michigan and
Colorado — and I can zoom into any place and open the photos taken there.
This realizes the "see it on a map" goal the location catalog was built for.

**Why this priority**: The location database (feature 002) proved 580+ items
carry coordinates; the map view is the payoff the family can actually touch.
Depends only on the P1 index.

**Independent Test**: After indexing, open the map view; verify located
items appear as pins/clusters at the places the archivist knows they were
taken (Grand Rapids home cluster, known trip locations), and that clicking
through opens the right photos.

**Acceptance Scenarios**:

1. **Given** the indexed library, **When** a family member opens the map
   view, **Then** items with embedded capture locations appear at their
   coordinates, clustered at sensible zoom levels.
2. **Given** a known trip (e.g., the Colorado or Michigan vacations),
   **When** the member zooms to that region, **Then** that trip's photos are
   there and open correctly.
3. **Given** items with no recoverable location, **When** the map is
   browsed, **Then** those items are simply absent from the map (never
   plotted at a wrong or placeholder position) while remaining fully
   visible in the timeline.

---

### User Story 4 - Find photos by content and people (Priority: P3)

As a family member, I search "beach", "birthday cake", or "dog" and get
relevant photos; I open the People section and see the family grouped by
face, so I can pull up every photo of Peepaw in seconds.

**Why this priority**: High-delight capability, but it depends on the NAS
having the compute headroom for content analysis — it must be able to run
after (or be deferred without blocking) the P1–P3 experience.

**Independent Test**: Run content analysis over the indexed library; issue
five known-answer searches ("beach" should surface the beach trip, etc.) and
confirm relevant results; confirm face groups exist for core family members
and that merging/naming a person works.

**Acceptance Scenarios**:

1. **Given** content analysis has completed, **When** a member searches a
   plain-language term matching known archive content, **Then** relevant
   items appear in the results.
2. **Given** face grouping has run, **When** the archivist names a person's
   face group, **Then** browsing that person shows their photos across the
   whole archive.
3. **Given** the NAS lacks compute headroom for analysis features, **When**
   they are disabled or deferred, **Then** timeline, map, and account
   capabilities continue to work fully.

---

### User Story 5 - New archive additions appear automatically (Priority: P3)

As the family archivist, when an Archivist run files new media (an iCloud
pull, a drop ingest), the new items show up in the family viewer without
anyone re-configuring anything — within a day at most, or on demand when I
trigger a rescan.

**Why this priority**: Keeps the viewer from going stale, completing the
pipeline: capture → Archivist verified filing → family browsing. Depends on
P1 and the established ingest flow.

**Independent Test**: Run a real Archivist ingest that files new items;
verify the new items appear in the viewer after the next scheduled or
manually triggered library scan, with correct dates and (where present)
locations.

**Acceptance Scenarios**:

1. **Given** an Archivist run files new media into the archive, **When** the
   run completes successfully, **Then** the tool triggers a viewer rescan
   automatically and the new items are browsable (with correct dates and
   locations) once that scan finishes — with the daily schedule as the
   backstop if the trigger cannot reach the viewer.
2. **Given** The Archivist moves condemned files to quarantine or purges
   them, **When** the next scan completes, **Then** those items no longer
   appear in the family view.

---

### Edge Cases

- Archive share unavailable to the viewer host (network/mount failure): the
  viewer serves its existing index (possibly stale) and MUST NOT treat
  missing files as deletions to propagate or purge; when the share returns,
  normal scanning resumes.
- Live Photo pairs (photo + motion clip) and RAW+JPEG pairs: displayed as a
  single logical item where the platform supports it — never as a broken or
  duplicated entry.
- Formats browsers can't natively show (HEIC stills, some video codecs): the
  viewer serves converted previews/transcodes generated and stored entirely
  outside the archive tree; originals remain untouched and downloadable.
- Items dated only by file timestamp (low confidence): they appear in the
  timeline at their best-guess date — consistent with the archive's own
  filing — not hidden or dumped in an "unknown" bucket.
- The tool's `_Quarantine` and any housekeeping directories inside the
  archive volume: excluded from indexing; if a quarantine run later purges
  files, nothing the family sees changes.
- A family member's device auto-upload feature: MUST remain disabled/unused —
  media enters the archive only through The Archivist; the viewer is not an
  ingest path.
- Viewer's own data (thumbnails, previews, analysis data, database): lives
  entirely on NAS storage outside the archive dataset; its growth or loss
  never affects archive files (a lost viewer index is rebuilt by
  re-scanning).
- Mixed orientation and very large videos (multi-GB): must stream/preview
  without requiring the original to be modified.

## Requirements *(mandatory)*

### Functional Requirements

**Read-only boundary (non-negotiable)**

- **FR-001**: The viewing layer MUST access the archive strictly read-only:
  no action available in any of its interfaces (user or administrative) may
  modify, move, rename, or delete an archived file. The read-only guarantee
  MUST be enforced at the storage-access level, not merely by interface
  policy.
- **FR-002**: All viewer-generated data (previews, thumbnails, transcodes,
  analysis results, its database) MUST be stored outside the archive tree,
  and the viewer MUST remain fully rebuildable from the archive by
  re-indexing.
- **FR-003**: The Archivist remains the sole ingest path: the viewer's
  upload/auto-backup capabilities MUST NOT be used to add media; the family
  archive MUST contain only Archivist-filed content.

**Indexing & display**

- **FR-004**: The viewer MUST index the complete archive (currently ≈5,300
  items / ≈3 TB, growing) and present it as a capture-date-ordered timeline
  with thumbnails and full-quality viewing, including formats that need
  server-side preview conversion.
- **FR-005**: The viewer MUST exclude the tool's quarantine and housekeeping
  directories from the family-visible library.
- **FR-006**: The viewer MUST re-scan the archive on a schedule (at least
  daily) and on demand, so items filed by an Archivist run appear without
  reconfiguration, and purged items disappear.
- **FR-006a**: The Archivist MUST trigger a viewer rescan automatically
  after every successful applying run (ingest, pull, cleanup, purge). The
  trigger is best-effort: if the viewer is unreachable, the archival run
  still succeeds (freshness falls back to the schedule) and the miss is
  noted in the run report.
- **FR-007**: Companion media (photo + motion clip pairs, RAW+JPEG) MUST
  display as single logical items where the platform supports pairing, never
  as broken entries.

**Map, search, people**

- **FR-008**: A map view MUST plot items by their embedded capture
  coordinates with sensible clustering; items without locations MUST simply
  be absent from the map (never plotted at placeholder coordinates).
- **FR-009**: When content analysis is enabled, family members MUST be able
  to search by plain-language content terms and browse automatically
  grouped, namable faces. These analysis features MUST be individually
  disableable (e.g., for NAS resource limits) without affecting timeline,
  map, or accounts.

**Access & privacy**

- **FR-010**: Each family member MUST have their own account; only the
  archivist holds administrative rights. Non-admin accounts MUST NOT be able
  to reconfigure libraries, manage users, or remove library content.
- **FR-011**: The viewer MUST be reachable from family devices on the home
  network. Exposure beyond the home network is out of scope for this
  feature; no part of the library may be publicly reachable from the
  internet by default.
- **FR-012**: All viewer data and analysis MUST run on the family's own
  hardware; no archive content, location data, or analysis output is sent to
  third-party services. (Map display tiles may come from an online map
  service, consistent with the family's established policy.)

**Resilience**

- **FR-013**: If the archive share becomes unavailable to the viewer, the
  viewer MUST NOT interpret missing files as deletions (no index purging or
  destructive reconciliation); normal operation resumes when the share
  returns.

### Key Entities

- **Viewing Layer (Immich deployment)**: The self-hosted photo platform
  running on the family NAS; owns its own database and generated previews;
  holds zero authority over archive content.
- **External Library**: The viewer's read-only watch over the archive tree
  (minus excluded directories); the bridge between The Archivist's filing
  and the family's browsing.
- **Family Account**: One per family member; non-admin by default; the
  archivist is the sole administrator.
- **Viewer Index**: The viewer's derived record of archive items (dates,
  locations, analysis results, faces); disposable and rebuildable — the
  archive plus The Archivist's catalog remain the systems of record.
- **Excluded Areas**: `_Quarantine` and housekeeping paths inside the
  archive volume that must never be family-visible.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the first full index, 100% of archive media items
  (excluding deliberately excluded areas) are browsable in the timeline,
  and the count reconciles against The Archivist's inventory.
- **SC-002**: Archive integrity is provably untouched: a before/after hash
  comparison of a sampled archive subtree shows zero changed bytes after
  indexing, analysis, and a week of family browsing.
- **SC-003**: Every named family member (at least 4 accounts) can sign in
  from their own device on the home network and reach any photo in under
  30 seconds of browsing or searching.
- **SC-004**: The map view plots at least as many items as the location
  catalog reports as located (within 2%), and zero items appear at
  placeholder/invalid coordinates.
- **SC-005**: Media filed by an Archivist run is visible in the viewer
  within 30 minutes when the viewer is reachable (auto-triggered rescan),
  and within 24 hours in all cases (scheduled backstop) — with zero manual
  reconfiguration either way.
- **SC-006**: A deliberate attempt to delete an archived item through the
  viewer UI (admin and non-admin) results in zero change to the archive on
  disk.
- **SC-007**: With content analysis enabled, five known-answer searches
  (e.g., "beach", "snow", "birthday") each return relevant archive photos
  in their top results.

## Assumptions

- Immich is the family's chosen platform (decided in conversation
  2026-07-31), deployed on the existing family TrueNAS (Community Edition
  26.0.0-BETA.2, i3-1215U with Quick Sync, 7.5 GiB RAM, pool "cyberfarm")
  that already hosts the archive share — the viewer reads the archive
  dataset locally, not over the network. The 8 GB RAM ceiling means
  content analysis starts disabled (see Clarifications); if even core
  viewing proves unacceptable on this box, hosting moves to another
  always-on family machine — same read-only boundary either way.
- Access is home-network-only in this feature; remote access (VPN or
  similar) is a possible future feature and explicitly out of scope now.
- Content analysis (search, faces) runs only if the NAS has the compute
  headroom; it is enabled feature-by-feature and may be deferred without
  blocking delivery of timeline/map/accounts.
- The archive share can be presented to the viewer host read-only at the
  storage layer (enforcing FR-001 below the application).
- The Archivist's pipeline (001) and location catalog (002) are in place;
  nothing in this feature writes to The Archivist's catalog, and the viewer
  maintains its own independent index.
- Freshness comes from the auto-trigger after each applying run (see
  Clarifications); the daily schedule is a backstop, and a day of staleness
  is tolerable only in the trigger-failure case.
- Mobile auto-backup from family phones stays disabled as policy; iCloud
  pulls through The Archivist remain the ingest path for phone media.
