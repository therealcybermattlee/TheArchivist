# Research: Run The Archivist on a Linux Host (Proxmox)

**Feature**: 004-linux-proxmox-host | **Date**: 2026-07-31

No `NEEDS CLARIFICATION` markers remain. Decisions below resolve the
platform, storage-discipline, and deployment unknowns.

## D1. Python runtime — uv-managed CPython everywhere

- **Decision**: Install with `uv`; let uv provision CPython 3.12+ on the
  guest rather than depending on Debian's system Python. Same
  `uv sync` / `uv run archivist` workflow on all hosts.
- **Rationale**: Debian stable's Python lags (and mixing apt Python with
  project deps invites drift); uv gives byte-identical toolchain semantics
  on macOS and Linux — one fewer platform difference to test.
- **Alternatives considered**: apt Python + venv (version skew between
  Debian releases); Docker image (adds a third hosting flavor the spec
  doesn't ask for; LXC/VM parity is the requirement).

## D2. HEIC thumbnails — `pillow-heif`, dropping `sips`

- **Decision**: Add `pillow-heif` as a regular dependency; register it in
  `mapexport.py` (and the test fixture builder) so Pillow opens/saves HEIC
  natively on both platforms. Remove the `sips` code path entirely.
- **Rationale**: One cross-platform backend beats per-OS branches; the
  fixture builder also stops needing macOS, which is what lets the test
  suite run undoctored on Linux (FR-002). Removing `sips` on macOS too
  keeps the two hosts on the identical code path (SC-006 equivalence).
- **Alternatives considered**: keep `sips` on macOS + pillow-heif on Linux
  (two paths to test, no benefit); ImageMagick (`convert`) subprocess
  (heavier external dep, HEIC support varies by distro build).

## D3. RAW thumbnails — exiftool embedded-preview extraction

- **Decision**: For RAW formats (CR3/DNG/NEF/…), extract the embedded
  preview JPEG via exiftool (`-PreviewImage`/`-JpgFromRaw` binary output)
  and thumbnail that with Pillow. Cross-platform, no new dependency.
- **Rationale**: Virtually every RAW file carries a camera-generated JPEG
  preview; exiftool is already a hard dependency; this replaces the `sips`
  RAW path with something that works identically everywhere.
- **Alternatives considered**: `rawpy`/libraw (real decode — heavy native
  dependency for thumbnails we only need at 800 px); skipping RAW previews
  (degrades exports for camera sources unnecessarily).

## D4. Headless credential storage — gnome-keyring with hard refusal

- **Decision**: Document and provision `gnome-keyring` on the guest as the
  Secret Service backend for icloudpd's python-keyring (unlocked via PAM
  on login / `dbus-run-session` for SSH use). Add a keyring probe to the
  new `doctor` command and to `auth icloud`: if no functional secure
  backend exists, refuse with setup instructions — never fall back to
  plaintext or keyrings.alt (FR-010).
- **Rationale**: Secret Service is the Linux-native analog of macOS
  Keychain and the backend python-keyring auto-detects; PAM unlock makes
  it workable over SSH without a desktop. The refusal path keeps FR-010's
  no-plaintext promise honest even on a misprovisioned host.
- **Alternatives considered**: `keyrings.alt` file backend (obfuscated
  plaintext — explicitly forbidden); `pass`/GPG (extra tooling and GPG key
  ceremony for one secret); storing only session cookies and re-typing the
  password per pull (icloudpd wants a password provider for pulls;
  unacceptable friction for "run the update often").

## D5. Windowed incremental pulls — per-source last-pull state

- **Decision**: Store per-source pull state in the catalog's existing
  `meta` table (`pull_state:<source>` → ISO date of last successful pull
  completion). Routine pulls default to
  `--skip-created-before (last_pull − overlap)` with a 7-day overlap;
  `--recent N` / explicit `--since` still available; first-ever pull on a
  host without state requires an explicit window or `--full` (bootstrap
  acknowledgement). Catalog dedup remains the correctness net — any
  re-downloaded overlap files zero new items (FR-015).
- **Rationale**: icloudpd's native incrementality depends on mirror files
  staying on disk; with pruning, date windows replace file presence as the
  "what's new" signal. The overlap absorbs clock skew and late-arriving
  cloud items; dedup makes overlap harmless. State lives in the catalog so
  it migrates with the copy path and rebuilds honestly (a rebuilt catalog
  without state simply forces an explicit window).
- **Alternatives considered**: keeping full persistent mirrors (violates
  the 50 GB budget clarification); `--until-found` against pruned mirrors
  (broken by pruning — it counts files already on disk); tracking state in
  a separate file (another thing to migrate; meta table already exists).

## D6. Staging prune — `prune-staging`, triple-guarded

- **Decision**: New `staging.py` + `archivist prune-staging [--apply]`
  following the cleanup/purge shape: PLAN lists each staged file with its
  verification status; APPLY deletes only files that pass ALL of:
  (1) path is inside the tool's own staging/mirror area (resolved,
  symlink-refusing containment check), (2) full SHA-256 matches a catalog
  row whose `archive_path` is non-null, (3) that archived file exists on
  the mounted archive right now. Journals every deletion (JSONL manifest)
  before the unlink; dry-run by default; volume guard required (needs the
  archive mounted for check 3).
- **Rationale**: This is the feature's only new deletion path, so it gets
  the purge treatment: verified-counterpart-or-refuse, own-area-only,
  plan/apply/journal. Check 3 (archived copy present *now*) means a prune
  can never race a quarantine/purge into deleting the last copy.
- **Alternatives considered**: auto-prune after each successful ingest
  (silent deletion violates plan-before-destructive); TTL-based cleanup
  (age says nothing about whether the archive has the bytes).

## D7. Case-sensitivity hardening

- **Decision**: Audit and fix the collision path for case-sensitive
  filesystems: `_collision_free` gains a case-insensitive comparison
  against existing sibling names and already-planned destinations, so
  `IMG_1.JPG` and `img_1.jpg` (different content) get suffixes rather than
  coexisting as case-twins — keeping archive layout portable across the
  NAS's share semantics. Grouping already case-folds stems (no change).
  Fixture tests cover: case-twin different-content files, case-twin
  byte-identical duplicates, and scan of an archive containing case-variant
  names.
- **Rationale**: The archive is accessed via SMB (case-insensitive-ish)
  today and NFS (case-sensitive) tomorrow; folding collision checks keeps
  one file per logical name regardless of transport, which is what dedup
  and human browsing both assume.
- **Alternatives considered**: leaving Linux fully case-sensitive (risks
  case-twin files that SMB clients then can't distinguish); renaming
  existing archive content (out of scope, tool never renames history).

## D8. Config validation & `doctor`

- **Decision**: `config.load_config` fails fast when `archive_root` /
  `work_root` don't exist on this host, with a message naming the host and
  the likely cause (e.g., Mac-style `/Volumes/…` path on a Linux guest).
  New read-only `archivist doctor` command reports: config paths, volume
  guard status, required executables (exiftool, ffmpeg/ffprobe, icloudpd)
  with versions, keyring backend functionality, tzdata resolution of the
  configured timezone, and working-storage usage vs. the 50 GB budget.
- **Rationale**: FR-007's fail-fast plus a one-command health view makes
  both the migration guide and the validation checklist executable instead
  of prose.
- **Alternatives considered**: folding everything into `status` (status is
  the operator's daily view; doctor is provisioning-time — different
  audiences, and status stays fast by not probing executables).

## D9. Mounts & provisioning (VM reference, LXC second)

- **Decision**: Reference VM: Debian stable, small system disk + 50 GB
  ext4 working disk (guest-local), archive mounted via NFS from TrueNAS
  (`vers=4`, hard mount) at `/mnt/archive`; sentinel files work unchanged.
  LXC variant: host mounts the NFS share, bind-mounts it and a 50 GB
  host-side volume into the container (documented for both privileged and
  unprivileged-with-idmap setups). All of this lives in `docs/linux-host.md`
  — the tool sees only config paths (FR-013).
- **Rationale**: NFS-to-TrueNAS is the native, permission-clean transport
  for a Linux guest (vs. SMB's mode-bit shims); hard mounts make I/O block
  rather than silently error mid-copy, which pairs correctly with the
  guard's halt-on-disconnect behavior. Guest-local working disk is the
  simple choice at 50 GB (per clarification, either was acceptable).
- **Alternatives considered**: SMB from the guest (double-translation of
  permissions; NFS is already exported for the user's replication
  workflow); NAS-backed working dataset (fine too, but guest-local keeps
  staging churn off the NAS and the disk is trivially small).

## D10. Timezone independence

- **Decision**: Keep all date logic on the configured `default_timezone`
  (already the case via `tzdata`/`zoneinfo`); add tests that run the
  resolver and filing-path derivation under several `TZ` environment
  values (UTC, US/Eastern, Asia/Tokyo) asserting identical outputs; the
  migration guide sets the guest clock to UTC + NTP as a norm.
- **Rationale**: SC-007 demands identical filing regardless of host
  timezone; the code should already comply — the tests make it a proven
  invariant instead of an assumption.
- **Alternatives considered**: requiring the guest be set to Eastern
  (hides bugs instead of proving independence).

## D11. Immich trigger portability (cross-feature note)

- **Decision**: The 003 rescan trigger (not yet implemented) will be plain
  HTTP to the NAS-local Immich endpoint — no platform dependence; note it
  in the migration guide's checklist so it gets verified from the Linux
  host when 003 lands. Nothing to build in 004.
- **Rationale**: Avoids sequencing coupling between 003 and 004.

## D12. Validation strategy

- **Decision**: The migration guide ends with a numbered validation
  checklist (mirrored in quickstart.md): doctor green → suite green →
  guard refusals with unmounted NFS → fixture-drop ingest parity →
  windowed pull + re-run no-op → prune plan/apply safety → map export
  with HEIC/RAW previews → SC-007 TZ test. The same checklist runs on
  macOS (regression), the VM (reference), and the LXC (portability),
  satisfying SC-003 mechanically.
- **Rationale**: One checklist, three hosts — parity by execution, not by
  assertion.
