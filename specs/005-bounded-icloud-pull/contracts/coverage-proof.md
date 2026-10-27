# Contract: Coverage Proof & the Advance Decision

**Feature**: 005-bounded-icloud-pull | **Date**: 2026-09-26

This is the feature's core contract and its main test surface. It defines what
the tool will accept as proof that a download step covered its window, and the
exact mapping from (run mode × proof × ingest outcome) to advance-or-refuse.

Source findings for every signal below are in [research.md](../research.md) R1
and R2, taken from icloudpd v1.32.3 `src/icloudpd/base.py`.

---

## 1. Capturing the stream

The download step currently inherits the terminal
(`subprocess.run(cmd)` in `icloud.download`). It must instead **capture**
stdout and stderr, line by line, while the process runs.

- The downloader is invoked with `--log-level debug` regardless of the
  operator's chosen verbosity. The debug lines are the evidence; whether the
  operator sees them is a separate decision.
- Lines are streamed, not buffered to completion, so a long sweep can report
  progress and so a hung run is diagnosable.
- At default verbosity the tool prints its own periodic progress line and
  discards the raw stream. With `--verbose`, raw lines are passed through
  unmodified (FR-025).
- Capture must not deadlock on a full pipe: read continuously rather than
  waiting for exit.

## 2. Signals

| Signal | Level | Pattern (substring / regex intent) | Meaning |
|---|---|---|---|
| Completion | INFO | `All <phrase> have been downloaded` where `<phrase>` ∈ {`photos`, `videos`, `photos and videos`} | Iteration ran to its end without cancellation |
| Skip-before-cutoff | DEBUG | `Skipping <file>, as it was created <ts>, before <cutoff>.` | Enumeration reached an item older than the cutoff |
| Skip-after-cutoff | DEBUG | `Skipping <file>, as it was created <ts>, after <cutoff>.` | Upper-bound filter hit (historical slices only) |
| Until-found exit | INFO | `Found <n> consecutive previously downloaded photos. Exiting` | Loop broke early on the already-downloaded counter |
| Downloaded | INFO | per-item download line | Increment `downloaded` |
| Already present | DEBUG/INFO | per-item already-exists line | Increment `already_present` |

**Counting rule**: `examined` = downloaded + already_present + all skip lines.
It is a lower bound on what the downloader considered and is used only for
reporting, never for a decision.

### 2.1 Completion proves iteration ended, not that the library was scanned

Critical and easy to get wrong. Under `--recent N` the iterator is truncated by
`itertools.islice`, so the loop ends *normally* and the completion message is
still emitted. Completion therefore means "the downloader finished the work it
was asked to do", not "the whole collection was examined".

Consequences:

- For unbounded modes (`RECONCILE`, `BOOTSTRAP_FULL`, `EXPLICIT_SINCE`)
  completion **is** sufficient proof of window coverage.
- For `ROUTINE_BOUNDED` it is **not**. A second signal is required: at least
  one skip-before-cutoff line, which proves enumeration reached past the
  requested cutoff and therefore examined everything newer.

## 3. `CoverageProof`

```python
@dataclass(frozen=True)
class CoverageProof:
    enumeration_complete: bool   # completion signal observed
    reached_before_cutoff: bool  # >=1 skip-before-cutoff observed
    until_found_exit: bool       # loop broke on the already-downloaded counter
    examined: int
    downloaded: int
    already_present: int
    exit_code: int
    session_present_before: bool # cookie artifact existed pre-run (necessary, not sufficient)
    parser_confident: bool       # False => fail closed
    notes: tuple[str, ...]       # human-readable reasons, printed on refusal
```

### 3.1 Fail-closed conditions

`parser_confident` is `False` — and the run may not advance any watermark —
when any of:

- the session artifact was absent before the run began (checked pre-flight, so
  a dead session costs seconds rather than a full enumeration);
- the downloader version is not in the tested set (warn once, then refuse);
- `exit_code != 0`;
- no completion signal **and** no until-found exit was observed;
- the process was killed or the stream ended mid-line.

The log strings are not a stable upstream API. Failing closed means an upstream
rewording degrades to "watermarks stop advancing and the run says why" —
noisy and visible — rather than silent loss. This is the deliberate failure
direction for the whole feature.

## 4. The advance decision

```python
def decide_advance(
    mode: PullMode,
    proof: CoverageProof,
    ingest: IngestOutcome,
    *,
    applying: bool,
    previous_watermark: datetime | None,
    window_since: date | None,
) -> Decision
```

`Decision` is either `Advance(claimed_through=run_started)` or
`Refuse(reason: str)`. The reason string is what FR-008 prints.

### 4.1 Universal preconditions

Evaluated first, in order. The first failure wins and names the refusal.

| # | Precondition | Refusal reason |
|---|---|---|
| 1 | `applying` is true | `dry-run — no state written` |
| 2 | `mode` is not `INGEST_ONLY` | `--no-download: coverage not attempted` |
| 3 | `mode` is not `NARROW` | `bounded by <flag> — did not cover the window` |
| 4 | `proof.parser_confident` | `download step could not be confirmed: <notes>` |
| 5 | `proof.enumeration_complete` | `enumeration did not complete` |
| 6 | `ingest.failed == 0` | `<n> file(s) failed to copy` |

### 4.2 Per-mode requirements

Applied after the universal preconditions pass.

| Mode | Additional requirement | Refusal reason |
|---|---|---|
| `ROUTINE_BOUNDED` | `proof.reached_before_cutoff` | `scan bound (<n>) reached without clearing the window — raise scan_bound for this source` |
| `RECONCILE` | none | — |
| `BOOTSTRAP_FULL` | none | — |
| `EXPLICIT_SINCE` | `window_since <= previous_watermark` (or watermark absent) | `--since <d> starts after the current watermark <w> — would skip <w>..<d>` |
| `NARROW` | unreachable (precondition 3) | — |
| `INGEST_ONLY` | unreachable (precondition 2) | — |

### 4.3 The null-ingest case

A run may reach the decision with no ingest result at all — the mirror held no
files because nothing was downloaded. This is the 2026-09-26 shape, and also
the shape of a perfectly healthy quiet source.

**Rule**: a null ingest result is *not itself* a refusal. It is discriminated
by the proof:

- `enumeration_complete` and `downloaded == 0` → the source genuinely had
  nothing in the window. **Advance.**
- otherwise → preconditions 4/5 have already refused it.

This intentionally differs from FR-003's literal wording, which would strand a
quiet source in a forever-widening window. See [research.md](../research.md)
R6 for the proposed FR-003 amendment; `/speckit-analyze` must reconcile spec
and contract before implementation.

### 4.4 Reconciliation watermark

Advances only when **all** hold: `mode ∈ {RECONCILE, BOOTSTRAP_FULL}`, the
coverage decision was `Advance`, and `ingest.failed == 0`. A `ROUTINE_BOUNDED`
run never advances it regardless of outcome.

## 5. Write ordering

Per source, per applying run:

1. Build the `CoverageRecord` from mode, proof, ingest outcome and decision.
2. **Append it to `logs/pull-<run_id>.jsonl` and flush.**
3. If `Advance`: write `pull_state:<source>` (and `reconcile_state:<source>`
   when §4.4 applies) and `coverage:<source>`, then commit.

Journal before catalog, per Constitution Principle IV. An interruption between
2 and 3 leaves the journal authoritative and the watermark stale, which
re-covers ground on the next run rather than losing it.

## 6. Required tests (FR-033)

Each row is a contract test. Parsing tests run against recorded fixture streams
— no test contacts a real account.

| # | Case | Expected |
|---|---|---|
| 1 | Completion line present, exit 0 | `enumeration_complete` true |
| 2 | Each of the three completion phrasings | all recognised |
| 3 | No completion line, exit 0 | fail closed, refuse |
| 4 | Exit non-zero with completion line present | fail closed, refuse |
| 5 | Untested downloader version | warn once, refuse |
| 6 | Stream truncated mid-line | fail closed, refuse |
| 7 | `ROUTINE_BOUNDED`, complete, ≥1 skip-before-cutoff | advance |
| 8 | `ROUTINE_BOUNDED`, complete, zero skip-before-cutoff | refuse, names `scan_bound` |
| 9 | `NARROW` via each of `--recent`, `--until-found`, `--until` | refuse in all three |
| 10 | `INGEST_ONLY` | refuse |
| 11 | Dry-run, everything else perfect | refuse, no state written |
| 12 | Ingest failures present | refuse |
| 13 | Null ingest result, complete, `downloaded == 0` | advance (§4.3) |
| 14 | Null ingest result, incomplete enumeration | refuse — **the incident case** |
| 15 | `EXPLICIT_SINCE` with `since <= watermark` | advance |
| 16 | `EXPLICIT_SINCE` with `since > watermark` | refuse, names the skipped span |
| 17 | Advance | watermark equals run-start, not run-finish |
| 18 | Advance | journal entry written before the `meta` write |
| 19 | `RECONCILE` clean | both watermarks advance |
| 20 | `RECONCILE` with ingest failures | neither advances |
| 21 | `ROUTINE_BOUNDED` clean | coverage advances, reconcile does not |
| 22 | Constructed argument list, every mode | contains none of `--auto-delete`, `--delete-after-download`, `--keep-icloud-recent-days` (Principle I) |
| 23 | Session artifact absent pre-flight | refuse before invoking the downloader; note names the session dir |
