# Contract: Comparison and the No-Under-Report Invariant

This is the safety-critical contract of feature 006. Everything else is
plumbing around it.

## 1. The invariant

> **For every item genuinely absent from the archive, the comparison MUST report
> it missing. The comparison MAY report items that are in fact archived.**

Formally, with `A` = genuinely-unarchived items and `M` = reported missing:
`A ⊆ M`. Equality is not required and is not achievable (see §4).

**Why the asymmetry is non-negotiable.** A false "missing" costs a redundant
fetch that the ingest hash check discards — bandwidth, nothing more. A false
"present" lets `Reconciled` be claimed for a source that is not, advancing a
watermark past items that no future window will ever look at again. That is
the September 2026 failure, reproduced through a different door.

## 2. Comparison procedure

```
listed_rel   = { strip_prefix(p) for p in listing.paths }         # deduplicated
archived_rel = { strip_prefix(r) for r in catalog rows
                 where original_path LIKE '<mirror_prefix>%' }
missing      = sorted(listed_rel - archived_rel)
```

Where `mirror_prefix` is `<work_root>/<work_subdir>/staging/icloud/<source>/`.

**Three requirements on this procedure:**

1. **Prefix filtering is mandatory.** All sources share one staging tree. An
   unfiltered catalog query would let one account's rows mark another account's
   items present. (This is the same defect class as the pre-006 session check,
   which asked whether *any* account had signed in.)

2. **Comparison is on the relative path.** Absolute paths embed the work volume's
   mount point. A remount under a different name must not present an entire
   library as missing.

3. **The direction is one-way.** `archived_rel - listed_rel` is **not** computed
   as a finding. Items the archive holds that the library no longer does are
   expected and correct — the archive never deletes to match a source
   (Principle I). It MAY be reported as a diagnostic count; it MUST NOT affect
   the verdict.

## 3. Preconditions — all required before any verdict

| Precondition | On failure |
|---|---|
| Credentials usable for this account (`session_status`) | `Unverified`, **no network contact** |
| Downloader version is a tested one | `Unverified` |
| Listing completed (exit 0, no failure signal, final line well-formed) | `Unverified` |
| Mirror holds no files absent from the catalog | `Unverified` |

The last one is subtle and is the only identified route to a **false
`Reconciled`**: the listing omits files already present in the mirror, so a
downloaded-but-unfiled file is absent from both sides and the difference reads
empty. See research R7.

## 4. Known over-report sources — measured, accepted, documented

| Cause | Observed rate | Effect |
|---|---|---|
| Colliding target paths (two assets, one path; resolved by size suffix at fetch) | 13 in 6,100 (~0.2%) | Both reported missing though archived |
| Item filed as a duplicate of an earlier archived copy, recorded under that copy's path | not directly measured | Reported missing though archived |
| Filename altered by collision handling between runs | rare | Reported missing though archived |

None of these can produce the opposite error. Each arises from the archive
holding an item under a name the listing does not produce — which makes the item
*look absent*, never *look present*.

## 5. Verdict table

| Preconditions | `missing` | Verdict | `reconcile_state` | `audit_state` |
|---|---|---|---|---|
| any failed | — | `Unverified(reason)` | unchanged | unchanged |
| all passed | `0` | `Reconciled` | **advances** (under `--apply`) | advances |
| all passed | `> 0` | `Incomplete(report)` | unchanged | advances |

`audit_state` advancing on `Incomplete` is deliberate: the source *was* examined.
Without it a source with a standing gap would be re-enumerated every run forever.

## 6. Required tests

The invariant is proven, not asserted (constitution: Development Workflow).

- **Property test**: for random disjoint splits of a synthetic library into
  archived and unarchived sets, every unarchived item appears in `missing`.
- Listing truncated mid-line ⇒ `Unverified`, never `Reconciled`.
- Listing containing an error line among valid paths ⇒ `Unverified`.
- Empty listing + `complete` ⇒ `Reconciled`; empty listing + not `complete` ⇒
  `Unverified`.
- Another source's catalog rows present ⇒ must not reduce `missing`.
- Absolute prefix differs between listing and catalog ⇒ `missing` unchanged.
- Duplicate listed paths ⇒ counted once.
- Unfiled file in the mirror ⇒ `Unverified` even when the difference is empty.
- A missing path whose month is unreadable ⇒ appears in `undated`, and
  `by_month` + `undated` == `missing_count`.
