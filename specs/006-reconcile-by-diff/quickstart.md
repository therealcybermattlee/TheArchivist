# Quickstart: Validating Reconciliation by Enumeration Diff

How to prove this feature works, from fastest to most real. Everything in §1–§3
runs offline against fixtures; §4 touches live accounts.

## Prerequisites

```bash
cd /Users/mattlee/CodeStuff/TheArchivist
uv run pytest -q          # baseline before starting: 345 passing
```

For §4 only: both volumes mounted, and the source's credentials valid —
check without touching the network:

```bash
uv run python -c "
import sys; sys.path.insert(0,'src')
from pathlib import Path
from archivist.icloud import session_status
print(session_status(Path('/Volumes/ExternalBaseUnit/TheArchivist/icloud-session'),
                     'matt-public@example.com'))"
```

## 1. The invariant (fastest, most important)

The no-under-report property is the feature's safety contract:

```bash
uv run pytest tests/unit/test_gap_never_underreports.py -v
```

**Expected**: every case passes, including the property test over random
archived/unarchived splits. A failure here means a source could be marked
reconciled while items are missing — stop and fix before anything else.

## 2. Comparison and verdict logic

```bash
uv run pytest tests/unit/test_enumeration_parse.py \
              tests/unit/test_gap_compare.py \
              tests/unit/test_audit_verdict.py \
              tests/unit/test_repair_plan.py \
              tests/unit/test_audit_budget.py -q
```

**Expected**: all pass. Specifically confirm:

- a listing truncated mid-line yields `Unverified`, never `Reconciled`
- an error line among valid paths yields `Unverified` (research R2 — errors
  arrive on *stdout*)
- duplicate listed paths are counted once (R4)
- an unknown size estimate is treated as *over* budget, never under (FR-030)

## 3. CLI behaviour, offline

```bash
uv run pytest tests/integration/test_audit_cli.py \
              tests/integration/test_audit_unfiled_mirror.py \
              tests/integration/test_audit_session_gate.py \
              tests/integration/test_pull_all_audit.py \
              tests/integration/test_pull_all_autorepair.py -q
```

**Expected**: all pass. The two that matter most:

- `test_audit_session_gate` — an audit against unusable credentials makes **no
  subprocess call at all** (SC-008). Asserted by failing the test if `Popen` is
  reached.
- `test_audit_unfiled_mirror` — a mirror holding unfiled files cannot produce
  `Reconciled` even when the difference is empty (FR-008, research R7). This is
  the only known route to a false clean verdict.

## 4. Against a live source

Audit is read-only by default and transfers no media, so this is safe to run at
any time — but it does cost 10–20 minutes of provider queries.

**Start with a source known to be current.** As of 2026-10-27 all four are
covered through today, so any of them should come back clean.

```bash
archivist audit --source matt-public
```

**Expected**: a `listed N items` line, `nothing missing`, and — because `--apply`
was not given — *no* watermark change. Verify nothing moved:

```bash
sqlite3 /Volumes/ExternalBaseUnit/TheArchivist/catalog/archivist.sqlite3 \
  "select key||' -> '||value from meta where key like '%matt-public%';"
```

Then commit the result:

```bash
archivist audit --source matt-public --apply
```

**Expected**: `RECONCILED -> <timestamp>`, `reconcile_state:matt-public` now set,
`audit_state:matt-public` set, and a `kind: "audit"` record appended to
`logs/pull-<run_id>.jsonl`.

### Confirming zero media transfer (SC-001)

The claim that an audit costs no bandwidth should be measured, not believed:

```bash
du -sh /Volumes/ExternalBaseUnit/TheArchivist/staging   # before
archivist audit --source matt-public --apply
du -sh /Volumes/ExternalBaseUnit/TheArchivist/staging   # after — must be identical
```

### Proving a gap is detected

`matt-public` had a real gap from 2026-08-26 to 2026-10-26, repaired on
2026-10-26. To exercise detection without damaging anything, audit a source
*after* deliberately withholding a range from a disposable fixture catalog —
see `tests/integration/test_audit_cli.py`, which does exactly this offline.

Do **not** manufacture a gap against the live catalog.

## 5. Full suite

```bash
uv run pytest -q
```

**Expected**: 345 baseline plus the new tests, all passing, no skips beyond
those already declared.

## Rollback

Nothing in this feature deletes or overwrites archived media. If an audit
misbehaves, its effects are limited to two `meta` keys:

```bash
sqlite3 /Volumes/ExternalBaseUnit/TheArchivist/catalog/archivist.sqlite3 \
  "delete from meta where key like 'audit_state:%';"
```

Clearing `audit_state` forces a re-audit on the next run and loses nothing.
`reconcile_state` should be cleared only if an audit is believed to have
reconciled a source wrongly — in which case the journal record for that run
names exactly what it compared.
