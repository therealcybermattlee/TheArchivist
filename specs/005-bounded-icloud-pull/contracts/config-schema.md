# Contract: Configuration schema additions

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

Two new settings, both optional, both with documented defaults. Existing
`config.yaml` files remain valid with no edits — which matters because the
operator's live config is in use on a working archive.

---

## 1. Settings

| Setting | Scope | Type | Default | Meaning |
|---|---|---|---|---|
| `scan_bound` | per source, with global fallback | positive int | 500 | Items a routine refresh examines for this source before stopping (FR-019, FR-020). |
| `reconcile_interval_days` | per source, with global fallback | positive int | 30 | How stale this source's reconciliation watermark may become before a routine refresh escalates it to a full sweep (FR-013). |

Resolution order per source: source-level value → top-level value → built-in
default.

Defaults are justified against measured rates in
[research.md](../research.md) R7. Summary: the busiest source runs ~400
items/month, so a 500-item bound clears a month of its additions.

## 2. Shape

```yaml
# Optional top-level defaults for every icloud source.
scan_bound: 500
reconcile_interval_days: 30

sources:
  matt-personal:
    type: icloud
    device_folder: "Matt Personal Cell"
    username: "..."
    # Optional per-source overrides:
    scan_bound: 300

  matt-public:
    type: icloud
    device_folder: "Matt Public Cell"
    username: "..."
    scan_bound: 1500            # busiest library
    reconcile_interval_days: 14
```

## 3. Validation

Enforced at config load, alongside the existing validation, so a bad value is
refused before any volume is touched.

| Rule | On violation |
|---|---|
| `scan_bound` is an integer ≥ 1 | reject with the source key and offending value |
| `reconcile_interval_days` is an integer ≥ 1 | reject with the source key and offending value |
| Either key present on a non-`icloud` source | reject — it has no meaning there, and silently ignoring it hides a typo |
| Unreasonably small `scan_bound` (< 50) | accept, but warn once per run that refused advances are likely |

## 4. Migration

None required.

- Absent `scan_bound` → 500.
- Absent `reconcile_interval_days` → 30.
- Absent `reconcile_state:<source>` in the catalog → the source is due
  (FR-016), so **the first routine refresh after this ships escalates every
  configured source to a full sweep.**

That last point is the intended repair mechanism for the 2026-09-26 holes, but
it makes the first post-deployment run long — four simultaneous sweeps,
including the ~40k-asset source. The run must announce this up front
(FR-014), and `config.example.yaml` plus the README should say so. An operator
who wants to stage it can run `--no-reconcile` and then reconcile sources one
at a time with an explicit `--full --apply`.

## 5. Unchanged

`archive_root`, `work_root`, `work_subdir`, `default_timezone`, and every
existing per-source field (`type`, `device_folder`, `username`) keep their
current meaning and validation.
