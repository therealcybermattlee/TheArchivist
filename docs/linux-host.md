# The Archivist on a Linux Host (Proxmox)

Migration and operations guide for running The Archivist on a Debian guest
on the family Proxmox host. The **Debian VM is the reference deployment**;
the LXC variant is validated second against the identical checklist.
Feature spec: `specs/004-linux-proxmox-host/`. Governing rules:
`.specify/memory/constitution.md`.

Cardinal rules, host-independent:
- Media's permanent home is ALWAYS the TrueNAS archive. The guest never
  keeps media — the working volume (~50 GB) is transient pass-through.
- Only ONE host runs applying commands at a time (the Mac remains a
  fallback/dev host). Never run `--apply` operations from both.
- Routine operation is frequent small pulls (`archivist pull all --apply`,
  or `pull icloud --source X --apply` for one account, both using the
  stored window) plus periodic `archivist prune-staging --apply`.
  `pull all` is the cron-shaped entry point: it exits non-zero if any
  source failed, so a scheduled run surfaces problems instead of
  silently skipping an account.

## 1. VM provisioning (reference deployment)

Proxmox guest: Debian stable (netinst), 2 vCPU / 2 GB RAM is plenty.

**Disks**
- System disk: 16 GB.
- Working disk: 50 GB, ext4, mounted at `/srv/archivist-work`
  (`/etc/fstab` by UUID). This is `work_root`.

**Clock**: UTC + NTP (`timedatectl set-timezone Etc/UTC`; systemd-timesyncd
on). Filing dates are governed by `default_timezone` in config.yaml — the
host TZ is deliberately irrelevant (proven by the test suite).

**Archive mount (NFS from TrueNAS)** — export the archive dataset to the
guest's IP from the TrueNAS UI, then:

```
apt install nfs-common
mkdir -p /mnt/archive
# /etc/fstab — hard mount: I/O blocks on share loss instead of erroring,
# which pairs with the tool's halt-on-disconnect guard behavior.
truenas.local:/mnt/cyberfarm/VideoStorage  /mnt/archive  nfs4  hard,noatime  0 0
mount /mnt/archive
```

**Tooling**

```
apt install exiftool ffmpeg curl
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv (manages Python itself)
uv tool install icloudpd
git clone <repo> ~/TheArchivist && cd ~/TheArchivist
uv sync
```

**Host config** — create `~/TheArchivist/config.yaml` for THIS host (do not
copy the Mac's paths):

```yaml
archive_root: "/mnt/archive"
work_root: "/srv/archivist-work"
default_timezone: "America/Detroit"
# sources: same map as the Mac's config
```

**Initialize**: the archive sentinel already exists (written by the Mac);
`archivist init-volumes` writes the working-volume sentinel and creates the
work-dir layout. Then run `archivist doctor` — everything required must be
green before proceeding (keyring will fail until §2 is done).

## 2. Credential storage (headless keyring)

Cloud sessions need a SECURE secret store. The tool refuses to
authenticate rather than ever touch plaintext (constitution / FR-010).

```
apt install gnome-keyring libsecret-1-0 dbus-user-session
```

Unlock at login so SSH sessions can use it (PAM):

```
# /etc/pam.d/login and /etc/pam.d/sshd — append:
auth     optional  pam_gnome_keyring.so
session  optional  pam_gnome_keyring.so auto_start
```

For a pure SSH workflow, run keyring-dependent commands inside a D-Bus
session: `dbus-run-session -- uv run archivist auth icloud --source ...`
(the pull commands need the same wrapper, or enable systemd user
lingering: `loginctl enable-linger <user>`).

Verify with `archivist doctor` — the `keyring` check must report a
SecretService backend and a passing round-trip. Sessions are **per-host**:
each account re-runs `archivist auth icloud --source <key>` once on the
guest (password + 2FA at the terminal).

## 3. LXC variant

Same tool, same config semantics; only storage presentation differs, and
it all lives host-side. Debian template container, 1 GB RAM.

- **Mounts**: the Proxmox HOST mounts the NFS share and provides a 50 GB
  volume; both are bind-mounted into the container:

  ```
  # /etc/pve/lxc/<id>.conf
  mp0: /mnt/pve/archive,mp=/mnt/archive
  mp1: /mnt/pve/archivist-work,mp=/srv/archivist-work
  ```

- **Privileged vs unprivileged**: privileged containers use the mounts
  directly. Unprivileged containers need UID mapping (idmap) so the
  container user owns the mounted trees; a wrong idmap surfaces as the
  volume guard refusing (`not writable`) — that refusal is the designed
  behavior, not a tool bug. Verify with `archivist doctor` after any idmap
  change.
- Everything else (§1 tooling, §2 keyring, config.yaml) is identical; the
  same config file works when the mount paths match.

## 4. State migration & cutover

What migrates: **`catalog/` and `logs/` only** (small). Cloud mirrors do
NOT migrate — staged media is transient; pulls resume with recent windows.
Cloud sessions do NOT migrate — re-auth per host (§2).

1. Finish any Mac-side bootstrap (full-library pulls) and prune its
   staging (`archivist prune-staging --apply` on the Mac).
2. Stop applying-operations on the Mac.
3. Copy state:
   `rsync -a mac:/Volumes/ExternalBaseUnit/TheArchivist/{catalog,logs}/ /srv/archivist-work/TheArchivist/`
4. On the guest: `archivist status` — totals, location coverage, and the
   review queue MUST match the Mac's numbers exactly. Pull state rides in
   the catalog, so bare `archivist pull icloud --source X` (or
   `archivist pull all`) works immediately.
5. The guest is now primary. The Mac remains a fallback: its catalog goes
   stale from this point — before EVER applying from the Mac again, rsync
   the state back or re-scan.

Rebuild path (alternative to copying): `archivist scan-archive` +
`archivist scan-locations` on the guest; pull state starts empty, so the
first pull per source needs an explicit `--recent`/`--since` window.

## 5. Validation checklist

Run per host — macOS (regression), VM (reference), LXC (portability).
Record date + result for each row. Scenario detail:
`specs/004-linux-proxmox-host/quickstart.md`.

| # | Check | macOS | VM | LXC |
|---|-------|-------|----|----|
| 0 | `archivist doctor` fully green (+ breakage probes fail correctly) | | | |
| 1 | `uv run pytest` — all pass, no undeclared skips | | | |
| 2 | Guard refusals with share unmounted / sentinel gone | | | |
| 3 | Filing parity fixtures (paths identical incl. case + TZ variants) | | | |
| 4 | Headless auth + windowed pull + re-run no-op (catalog populated FIRST) | | | |
| 5 | prune-staging plan/apply + all three refusal probes | | | |
| 6 | export-map with HEIC/RAW thumbnails, opens in Google Earth | | | |
| 7 | State migration parity (`status` numbers match) | | | |
| 8 | (LXC only) full re-run of 0–6 in the container | — | — | |

Month-after (SC-008): working storage < 50 GB; prune journals show zero
deletions of anything but verified-archived items.
