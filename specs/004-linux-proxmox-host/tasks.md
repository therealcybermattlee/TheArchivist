# Tasks: Run The Archivist on a Linux Host (Proxmox)

**Input**: Design documents from `/specs/004-linux-proxmox-host/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-interface.md, quickstart.md

**Tests**: Included — FR-002 makes the suite a first-class requirement, and the feature's only new deletion path (prune) demands purge-level test scrutiny.

**Organization**: Tasks are grouped by user story. Note that several tasks (T011, T018, T020, T022) require the Proxmox/VM environment and operator presence — they are validation gates, not pure code.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: [US1] parity, [US2] headless cloud + storage discipline, [US3] LXC portability, [US4] state migration

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The cross-platform dependency and doc skeleton everything builds on

- [X] T001 Add `pillow-heif` to `pyproject.toml` dependencies; register HEIF opener at import in `src/archivist/mapexport.py` and `tests/fixtures/build_fixtures.py` entry points; verify `uv sync` + import on macOS
- [X] T002 [P] Create `docs/linux-host.md` skeleton with section stubs (VM provisioning, keyring, LXC variant, state migration, validation checklist) to be filled by later tasks

**Checkpoint**: `uv run python -c "import pillow_heif"` succeeds; docs skeleton exists

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Platform-neutral media handling and catalog plumbing every story consumes

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Switch HEIC fixture creation in `tests/fixtures/build_fixtures.py` from `sips` to `pillow-heif` (create HEIC via Pillow save); drop `sips` from `tools_available()`; full suite still green on macOS
- [X] T004 Replace thumbnail backends in `src/archivist/mapexport.py`: HEIC/HEIF via pillow-heif (Pillow-native path), RAW via new `metadata.extract_preview(path) -> bytes | None` helper in `src/archivist/metadata.py` (exiftool `-PreviewImage`/`-JpgFromRaw` binary extraction), video via ffmpeg (unchanged); DELETE the `sips` code path; update `tests/unit/test_mapexport.py` for the new backend table
- [X] T005 [P] Add fail-fast root-path validation to `src/archivist/config.py` (`archive_root`/`work_root` must exist on this host; error message names the host and flags Mac-style `/Volumes/…` paths on Linux) with unit tests in `tests/unit/test_config_validation.py`
- [X] T006 [P] Add `get_meta(conn, key)` / `set_meta(conn, key, value)` helpers to `src/archivist/catalog.py` (for `pull_state:<source>` keys per data-model.md) with unit tests in `tests/unit/test_catalog_meta.py`

**Checkpoint**: suite green on macOS with zero `sips` references in the repository

---

## Phase 3: User Story 1 - Full workflow parity on a Debian guest (Priority: P1) 🎯 MVP

**Goal**: Every command, guard, and test behaves identically on a Debian VM — no macOS tooling anywhere

**Independent Test**: quickstart.md Scenarios 0–3 on the VM: doctor green, suite green, guard refusals on NFS, filing parity incl. case-sensitivity and TZ independence

- [X] T007 [US1] Harden collision policy for case-sensitive filesystems in `src/archivist/ingest.py` (`_collision_free`): case-insensitive comparison against existing sibling filenames and planned destinations so case-twin names with different content get hash suffixes on every platform; ALSO implement PLAN.md §E's unimplemented same-hash rule — on destination collision, hash-compare the existing file first: byte-identical → plan as skip-duplicate (never suffix), different content → suffix. This makes filing safe under incomplete/rebuilt catalogs (defense-in-depth for the T018 precondition). Unit tests in `tests/unit/test_collision_case.py` (case-twin different content → suffixed; case-twin byte-identical → duplicate skip; same-name same-hash existing dst → skip-duplicate; scan of case-variant archive names)
- [X] T008 [P] [US1] Add timezone-independence tests in `tests/unit/test_tz_independence.py`: date resolution and target-directory derivation produce identical results under `TZ=UTC`, `TZ=America/Detroit`, `TZ=Asia/Tokyo` (monkeypatched env) per SC-007
- [X] T009 [US1] Create `src/archivist/doctor.py` + `archivist doctor` command in `src/archivist/cli.py` per contracts: config-path validity, volume guard status, executable presence+versions (exiftool/ffmpeg/ffprobe/icloudpd), pillow-heif import, keyring secure-backend probe (set/get/delete throwaway secret), timezone resolution, working-storage usage vs 50 GB budget; exit 0 only when required checks pass; unit tests with mocked probes in `tests/unit/test_doctor.py`
- [X] T010 [US1] Write the VM provisioning + validation-checklist sections of `docs/linux-host.md`: Debian stable VM on Proxmox, NFS hard-mount of the archive share (vers=4) at `/mnt/archive`, 50 GB ext4 working disk, UTC+NTP, uv install, tool install, `init-volumes`, then the numbered checklist mirroring quickstart Scenarios 0–8
- [ ] T011 [US1] Provision the reference Debian VM per `docs/linux-host.md` and execute quickstart Scenarios 0–3 on it (doctor incl. deliberate-breakage probes, full suite, NFS guard refusals, filing parity/case/TZ); record results in the checklist section of `docs/linux-host.md` *(requires Proxmox access + operator)*

**Checkpoint**: The VM runs everything the Mac runs — MVP complete

---

## Phase 4: User Story 2 - Cloud pulls from the Linux host, headless (Priority: P2)

**Goal**: Windowed incremental pulls with per-source state, terminal-only auth with secure-storage-or-refuse, and the guarded staging prune that keeps the 50 GB budget honest

**Independent Test**: quickstart.md Scenarios 4–5 over SSH on the VM: auth + windowed pulls live, prune plan/apply with all three refusal probes, credential grep clean

- [X] T012 [US2] Implement windowed pulls in `src/archivist/icloud.py` + `src/archivist/cli.py`: read `pull_state:<source>` via catalog meta; bare `pull icloud` uses `--skip-created-before (last_pull − 7 days)`; stateless bare invocation refuses with guidance (require `--recent`/`--since`/`--full`); advance state only after successful download + ingest; unit tests in `tests/unit/test_pull_window.py` (window math, overlap, stateless refusal, no-advance-on-failure)
- [X] T013 [US2] Create `src/archivist/staging.py` prune engine per data-model.md: walk resolved staging roots (`staging/**`, `drops/**`; symlinks refused as `outside-staging`), derive per-file status (`verified-archived` = full SHA-256 matches catalog row with non-null `archive_path` AND that file exists on the mounted archive now; else `unverified` / `archived-missing`), build plan, apply deletes only `verified-archived` with JSONL journal line before each unlink to `logs/prune-<ts>.jsonl`
- [X] T014 [US2] Add `archivist prune-staging [--source] [--apply]` command in `src/archivist/cli.py` (volume guard required; plan rendering with reclaimable bytes and refusal reasons; `archived-missing` highlighted as archive-integrity warning) and add the working-storage usage line to `status`
- [X] T015 [P] [US2] Prune integration tests in `tests/integration/test_prune_staging.py`: ingest fixtures then prune (plan classifies, apply deletes only verified, journal complete); refusal probes — never-ingested drop file (`unverified`), renamed-away archived counterpart (`archived-missing` + warning), symlink escape (`outside-staging`); guard refusal with sentinel removed; re-run plan shows nothing prunable
- [X] T016 [P] [US2] Windowed-pull state integration tests in `tests/integration/test_pull_state.py` with mocked `icloud.download`: state advances on success only, bare pull uses stored window, stateless refusal end-to-end through the CLI
- [X] T017 [US2] Secure-storage enforcement: keyring probe shared between `doctor` and `auth icloud` (refuse auth with setup instructions when no functional secure backend — never plaintext) in `src/archivist/icloud.py`/`src/archivist/doctor.py`; write the gnome-keyring headless setup section (PAM unlock, `dbus-run-session` for SSH) in `docs/linux-host.md`
- [ ] T018 [US2] On the VM over SSH: execute quickstart Scenario 4 (terminal auth with 2FA, windowed pulls live against a real account, immediate re-run no-op) and Scenario 5 (prune plan/apply + safety probes live); verify `grep -ri password` clean across config/logs/manifests. **PRECONDITION: populate the VM catalog FIRST** (copy `catalog/` + `logs/` from the Mac per T021's copy path, or run `scan-archive` + `scan-locations` on the VM) — a live `--apply` pull against an empty catalog cannot recognize already-archived content and would re-file duplicates into the real archive *(requires operator for 2FA)*

**Checkpoint**: Routine pull-and-prune operation works headless within the storage budget

---

## Phase 5: User Story 3 - Same tool, either container or VM (Priority: P2)

**Goal**: The LXC variant reaches the identical validation checklist with the identical config semantics

**Independent Test**: quickstart.md Scenario 8 — full checklist in the LXC deployment

- [X] T019 [US3] Write the LXC section of `docs/linux-host.md`: host-side NFS mount + bind-mounts into the container (archive + 50 GB working volume), both privileged and unprivileged-with-idmap variants, explicit note that a bad idmap surfaces as a guard refusal (unwritable volume), and that no tool configuration differs from the VM beyond mount paths
- [ ] T020 [US3] Deploy the LXC variant per `docs/linux-host.md` and execute the full validation checklist (quickstart Scenarios 0–6) inside it; record results alongside the VM's in `docs/linux-host.md` (SC-003) *(requires Proxmox access + operator)*

**Checkpoint**: Hosting type is provably interchangeable

---

## Phase 6: User Story 4 - Bring the existing state along (Priority: P3)

**Goal**: Catalog + manifests migrate (or rebuild); Linux becomes the primary operator host

**Independent Test**: quickstart.md Scenario 7 — copy path parity of status/coverage numbers; rebuild path reconciliation

- [X] T021 [US4] Write the state-migration section of `docs/linux-host.md`: copy path (catalog/ + logs/ only — mirrors are transient and stay behind; sessions re-auth per host), rebuild path (`scan-archive` + `scan-locations`), the one-applying-host-at-a-time rule, and Mac-as-fallback posture
- [ ] T022 [US4] Finalize the migration/cutover: if the catalog was already copied for T018's precondition, refresh it with any Mac runs since; otherwise stop Mac applying-operations and copy `catalog/` + `logs/` now. Verify `status` totals/location coverage/review-queue match the Mac's exactly, verify bare `pull icloud` uses the migrated pull state, then declare the Linux guest primary *(requires operator)*

**Checkpoint**: Linux guest is the primary operator host with full history

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update `README.md` (Linux host support, `doctor`, `prune-staging`, windowed pulls, link to `docs/linux-host.md`) and `config.example.yaml` (Linux mount-path examples alongside the Mac ones)
- [X] T024 macOS regression pass: full suite plus quickstart spot-checks (export-map HEIC/RAW thumbnails via the new backends, ingest, doctor) on the Mac — proving `sips` removal and backend swaps changed nothing behaviorally (SC-006 both-platform equivalence)
- [ ] T025 Month-after audit (SC-008, deferred by nature): after ~30 days of routine Linux operation, record working-storage usage (< 50 GB) and audit prune journals for zero non-verified deletions; note results in `docs/linux-host.md` *(operator, future-dated)*
- [ ] T026 Add `--prune-verified` flag to `pull icloud --apply` in `src/archivist/cli.py`: after a fully successful ingest, run the staging prune scoped to that source with the identical verified-archived-only rules and journal (deletion explicitly requested in the same invocation — constitutionally clean). Decided 2026-08-01: manual `prune-staging` until the Linux live system is running; this flag becomes the routine-operation default there

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately
- **Foundational (Phase 2)**: needs T001; T003 → T004 (fixture builder proves pillow-heif before mapexport swap); T005 ∥ T006 independent
- **US1 (Phase 3)**: needs Phase 2; T011 (VM validation) additionally needs T009 + T010 and Proxmox access
- **US2 (Phase 4)**: needs Phase 2 (T006 for pull state); T013 → T014 → T015; T017 needs T009's probe; T018 needs T011's VM **and a populated VM catalog** (T021 copy procedure or a fresh scan) before any live `--apply` pull
- **US3 (Phase 5)**: needs US1's T010/T011 (VM-validated docs to vary from); T020 needs T019
- **US4 (Phase 6)**: T022 needs T011 (working VM) + ideally T018 (pulls proven); the full-mirror bootstrap + staging prune on the Mac should complete before cutover
- **Polish (Phase 7)**: T024 after all code tasks; T025 after T022 + ~30 days

### Story Dependency Notes

- Code tasks (T003–T009, T012–T017) are all writable on the Mac — the VM/LXC (T011, T018, T020, T022) are validation gates needing Proxmox + operator. A practical split: write all code first, then do the VM day, then the LXC day.
- `cli.py` is touched by T009, T012, T014 — serialize those three.

### Parallel Opportunities

```text
Phase 1: T001 → T002 ∥ (anything)
Phase 2: T003 → T004; T005 ∥ T006 alongside
Phase 3: T007 ∥ T008 → T009 → T010 → T011
Phase 4: T012 → T013 → T014 → T015 ∥ T016 → T017 → T018
Phase 5: T019 → T020
Phase 6: T021 → T022
```

---

## Implementation Strategy

**MVP first (US1)**: Phases 1–3 make the tool genuinely cross-platform and prove it on the reference VM — the Mac keeps working throughout (T024 guards that).

**Incremental delivery**: US2 brings the day-to-day workflow (pulls + prune) to the VM; US3 banks the portability guarantee; US4 flips the primary-host switch. Each checkpoint leaves both hosts functional.

**Operator-day batching**: T011 + T018 fit one "VM day" (provision, validate, auth, pull, prune); T020 is a shorter "LXC day"; T022 is the deliberate cutover moment — schedule it after the Mac-side full-library bootstrap finishes and its staging has been pruned.
