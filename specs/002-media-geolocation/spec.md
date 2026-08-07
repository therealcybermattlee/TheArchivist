# Feature Specification: Media Geolocation Catalog

**Feature Branch**: `002-media-geolocation`

**Created**: 2026-07-30

**Status**: Draft

**Input**: User description: "I want to build a database of WHERE the media was
taken when it exists as well so that later we could see it on a map to
interact with the photos."

## Overview

Much of the family's media carries embedded location information recorded by
the capturing device (phones especially; some cameras and drones). Today the
archive inventory records *when* each item was captured but discards *where*.
This feature extends the inventory to capture and preserve each item's
capture location whenever one exists — for media already in the archive and
for everything ingested from now on — so the family's collection becomes
map-ready: a future map experience (out of scope here) can plot the archive
and let the family explore photos by place. The location record follows the
same trust rules as the rest of the inventory: read from the media, never
written to it, and honest about what is unknown.

## Clarifications

### Session 2026-07-30

- Q: Should the archivist be able to manually assign or correct a media item's location in this feature? → A: Out of scope — this feature only captures embedded locations; manual assignment/correction is deferred to a future feature (e.g., alongside the map viewer or review workflow).
- Q: How should the interactive map viewer relate to this feature's scope? → A: Separate next feature — this feature stays database + map-ready export, with a clickable-photo export for Google Earth desktop as the preview; a custom family map viewer becomes its own follow-on feature built on this database.
- Q: Should a future viewer be allowed to use online map services (e.g., Google Maps tiles/API) for display and enrichment? → A: Yes — photos and the location database stay local, but map display/enrichment in the future viewer may use online map services; this feature itself still transmits nothing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Backfill locations for the existing archive (Priority: P1)

As the family archivist, I run an inventory update over the already-archived
library and the tool records the capture location (latitude/longitude, plus
altitude when present) for every item that carries one, without moving,
modifying, or re-copying any archived file. Items without location data are
recorded as having none — silently absent data, not an error.

**Why this priority**: The existing archive holds a decade-plus of media —
that's where most of the mappable memories already live. Without backfill,
the location database would only ever describe new ingests.

**Independent Test**: Run the location update against the mounted archive;
spot-check a sample of phone photos with known locations and confirm the
recorded coordinates match; confirm files' bytes and timestamps are
untouched; confirm items known to lack location (e.g., old scanned photos)
are marked location-absent.

**Acceptance Scenarios**:

1. **Given** the archive contains media with embedded location metadata,
   **When** the archivist runs the inventory location update, **Then** each
   such item's inventory record gains its capture coordinates (and altitude
   when present) along with where the location came from.
2. **Given** an archived item has no recoverable location, **When** the
   update runs, **Then** the item is recorded as location-absent and is not
   flagged as an error.
3. **Given** the update was interrupted or new items were archived since the
   last run, **When** the update runs again, **Then** already-processed items
   are not re-read from scratch and the location coverage reflects the
   current archive.
4. **Given** any location update run, **When** it completes, **Then** no
   archived file has been modified, moved, or re-copied — the archive bytes
   are exactly as before.

---

### User Story 2 - Capture location during every new ingest (Priority: P2)

As the family archivist, when I ingest new media (folder drops, device
cards, cloud pulls), each item's capture location is extracted and stored in
the inventory as part of the normal ingest flow — no extra step, no separate
pass.

**Why this priority**: Going forward, location capture must be automatic so
coverage never decays. It builds on the existing ingest pipeline and on the
inventory shape established by Story 1.

**Independent Test**: Ingest a sample folder containing located phone
photos, a located video, and unlocated media; confirm located items carry
correct coordinates in the inventory, unlocated items are marked
location-absent, and the run report includes location coverage counts.

**Acceptance Scenarios**:

1. **Given** a source folder with location-bearing media, **When** it is
   ingested, **Then** each filed item's inventory record includes its
   capture coordinates without any additional operator action.
2. **Given** a companion group (photo + motion clip, image + sidecar),
   **When** it is ingested, **Then** the group shares one location taken
   from its best-located member, so the pair never lands in two places on a
   future map.
3. **Given** an ingest run completes, **When** the run report is shown,
   **Then** it includes how many filed items had a location and how many did
   not.

---

### User Story 3 - See and share location coverage (Priority: P3)

As the family archivist, I can ask the tool how location coverage looks —
how many items have locations, by year and by source — and export the
located items (coordinates plus each item's date and archive location) in a
form a mapping tool can consume, so the family can preview the "photos on a
map" future before a dedicated map experience exists.

**Why this priority**: Visibility proves the database is filling and makes
the data immediately useful, but it depends entirely on Stories 1–2 having
populated it.

**Independent Test**: After backfill, request the coverage summary and
confirm counts match reality on a sampled year; export the located items
and load the export in a common mapping application to see the archive
plotted.

**Acceptance Scenarios**:

1. **Given** a populated location database, **When** the archivist requests
   the status view, **Then** it reports located vs. unlocated counts overall
   and broken down by year and by source.
2. **Given** located items exist, **When** the archivist requests a location
   export, **Then** the tool produces an export of located items
   (coordinates, capture date, archive path) that opens in Google Earth
   desktop with each item as a clickable pin showing the photo, without
   modifying the archive or inventory.

---

### Edge Cases

- Coordinates that are present but meaningless — the (0, 0) "null island"
  placeholder some devices write, or values outside valid
  latitude/longitude ranges: rejected as evidence; the item is recorded as
  location-absent, with the rejection noted.
- Companion group members with conflicting locations (e.g., photo has GPS,
  paired clip has none or differs slightly): the group takes the location of
  its best-located member — the same "best-dated member governs the group"
  principle already used for dates.
- Media whose location was stripped by an intermediary (e.g., re-exported or
  messaging-app copies of an original that had GPS): recorded as
  location-absent; no attempt is made to guess a location from other files.
- Duplicate content where one copy carries location and another does not:
  the inventory keeps the location from whichever copy provides it, so
  deduplication never erases a known location.
- Videos with location recorded only at recording start: that single point
  is used as the item's location.
- Interrupted backfill runs: resume without re-reading completed items;
  coverage numbers only ever count completed extractions.
- Location data is sensitive family data: it lives only in the local
  inventory and exports the archivist explicitly creates; nothing in this
  feature sends locations to any external service (the future viewer may
  use online map services, per Clarifications).

## Requirements *(mandatory)*

### Functional Requirements

**Location capture**

- **FR-001**: The system MUST record, for every inventoried media item, its
  capture location (latitude, longitude, and altitude when present) whenever
  the item carries recoverable embedded location metadata, along with the
  source of that location.
- **FR-002**: The system MUST record items without recoverable location as
  location-absent — a normal state, not an error — and MUST NOT invent or
  infer coordinates from other items, file paths, or external services.
- **FR-003**: The system MUST reject implausible coordinates (out-of-range
  values and the (0, 0) placeholder) as evidence and record the item as
  location-absent with the rejection noted.
- **FR-004**: A companion group MUST carry a single group location taken
  from its best-located member, consistent with how group dates are
  resolved.

**Backfill & ongoing capture**

- **FR-005**: The system MUST be able to populate locations for
  already-archived media by reading archived files in place — never
  modifying, moving, or re-copying them — and MUST make repeat runs
  incremental (already-processed items are not re-read from scratch).
- **FR-006**: All ingest pathways (folder, drops, device, cloud pull) MUST
  extract and record location as part of the standard ingest flow, with no
  separate operator step.
- **FR-007**: When byte-identical duplicate copies are encountered, the
  inventory MUST retain a location if any copy provides one; duplicate
  handling MUST never erase a known location.

**Visibility & export**

- **FR-008**: The status view MUST report location coverage: counts of
  located vs. unlocated items, overall and by year and by source.
- **FR-009**: Each ingest or update run's report MUST include how many
  processed items gained a location and how many were location-absent.
- **FR-010**: The system MUST export located items (coordinates, capture
  date, archive path, and item identity) on request in a form that Google
  Earth desktop can open with each item as a clickable pin displaying the
  photo (generating viewable thumbnails for formats the viewer cannot show
  natively); the export and its thumbnails are generated products written
  outside the archive, and producing them MUST NOT alter the archive or the
  inventory.

**Safety & privacy (inherit the archive's invariants)**

- **FR-011**: Location capture MUST never modify any source or archived
  file; all existing safety invariants (read-only sources, guarded volumes,
  plan-before-apply for anything that writes) apply unchanged.
- **FR-012**: Location data MUST remain local within this feature: stored
  only in the family's inventory and in exports the archivist explicitly
  creates, and no capability in this feature transmits locations to any
  external service (place-name lookup is out of scope here). This does not
  bind the future map viewer, which may use online map services for display
  and enrichment while photos and the location database stay local.

### Key Entities

- **Capture Location**: The place a media item was captured — latitude,
  longitude, optional altitude — plus the evidence source it came from and
  whether location is present, absent, or rejected-as-implausible. Attached
  to each Media Item in the existing inventory.
- **Media Item** *(existing, extended)*: Gains its Capture Location
  alongside the existing date, identity, and device attributes.
- **Asset Group** *(existing, extended)*: Gains a single group location
  from its best-located member, governing future map placement of the whole
  group.
- **Location Export**: A generated product (location file plus any needed
  photo thumbnails) of located items — coordinates + capture date + archive
  path — that opens in Google Earth desktop with clickable photo pins;
  written outside the archive, never altering archive or inventory.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After backfill, 100% of archived media items that carry
  readable embedded location metadata have coordinates recorded in the
  inventory (verified by sampling across years and devices).
- **SC-002**: Zero archived or source files are modified by location
  capture — archive bytes identical before and after any backfill or
  update run.
- **SC-003**: A full location backfill of the existing archive (≈5,500
  items, ≈3 TB) completes in a single sitting on the archivist's setup —
  under 2 hours — and repeat runs complete in minutes.
- **SC-004**: 100% of newly ingested location-bearing items receive
  coordinates automatically, with no separate operator step, from the first
  ingest after this feature ships.
- **SC-005**: Recorded coordinates are accurate: for a 50-item verification
  sample of media with independently known capture places, every recorded
  location falls at the expected place (within normal consumer GPS
  tolerance), and zero items carry rejected/implausible coordinates.
- **SC-006**: The location export, opened in Google Earth desktop, plots
  every exported item as a pin, and clicking a pin displays that item's
  photo — demonstrating end-to-end map-readiness before the dedicated
  viewer exists.

## Assumptions

- The interactive map experience ("see it on a map to interact with the
  photos") is the next feature, specified separately and built on this
  location database: a custom family viewer that may use online map
  services (e.g., Google Maps) for display and enrichment while photos and
  the database stay local. This feature delivers the database and the
  Google Earth preview export, not the viewer.
- Coordinates only, no place names in this feature: reverse geocoding
  (turning coordinates into "Traverse City") requires external services and
  is deferred to the future viewer, which is permitted to use them.
- Only embedded/declared location evidence is used (media metadata and,
  where present, cloud/export sidecar records); the system never infers
  location from folder names, event names, or nearby items.
- Manual location assignment or correction by the archivist is out of scope
  for this feature; it is deferred to a future feature (a natural companion
  to the map viewer or the date review workflow).
- Most older media (scans, early cameras, GoPro footage without GPS enabled)
  legitimately has no location; coverage is expected to be partial and
  concentrated in phone-era media.
- The existing inventory, ingest pipeline, and safety invariants from the
  baseline (001-archivist-baseline) are in place; this feature extends them
  rather than introducing new pathways.
- One operator (the family archivist) on one machine, consistent with the
  baseline.
