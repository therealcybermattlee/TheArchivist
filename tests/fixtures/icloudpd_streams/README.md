# Fixture provenance

The DEBUG skip line and the INFO completion line are transcribed verbatim from
a real 2026-09-26 `archivist pull all --apply` run against icloudpd 1.32.3 (the
run that motivated feature 005).

Every other line is transcribed from the upstream v1.32.3 format strings in
`src/icloudpd/base.py`, NOT invented:

| Event | Format string | Note |
|---|---|---|
| already present | `"%s already exists"` | **no trailing period** |
| per-item download | `"Downloaded %s"` | **past tense** |
| preamble (once) | `"Downloading %s %s %s to %s ..."` | count is `the first` only when N==1, else the number, else `???` |
| completion | `"All %s have been downloaded"` | phrase varies: photos / videos / photos and videos |
| until-found exit | `"Found %s consecutive previously downloaded photos. Exiting"` | |

## Why this file exists

The first version of these fixtures was written from *guessed* wording, and the
parser was then tested against the guesses. It passed 272 tests while being
wrong about three of the five signals: it required a period after
`already exists`, matched the present-tense `Downloading` for per-item events
(upstream emits `Downloaded`), and recognised the preamble only in its
singular form — so on any real multi-item run it counted the banner as a
download and every genuine download as nothing.

A parser tested only against its author's assumptions confirms the assumptions,
not the behaviour. Both preamble forms (singular and numeric) and the
period-less `already exists` are now pinned here deliberately.

No live iCloud account was contacted to build these. The parser must stay
tolerant of wording it has not seen: anything it cannot positively confirm
fails closed (`CoverageProof.parser_confident`).

## Enumeration fixtures (feature 006)

`enumeration-*.log` capture `--only-print-filenames` output, whose shape differs
from an ordinary run's in three ways that matter:

| Fixture | Represents |
|---|---|
| `enumeration-sample.log` | A healthy listing: absolute target paths, one per line, nothing else |
| `enumeration-truncated.log` | A listing cut off mid-line — ends without a newline |
| `enumeration-auth-error.log` | Valid paths followed by a failure **on stdout** |
| `enumeration-empty.log` | A library with no items (legitimate when the run completed) |

`enumeration-sample.log` is derived from a real listing of the `matt-public`
library captured 2026-10-26 (6,100 lines, cancelled part-way). Filenames are
replaced with synthetic `ASSET_NNNN` names; the **shape** is preserved — the
`{:%Y/%m}` folder structure, HEIC+MOV live-photo pairing, and the colliding
duplicate pair where two distinct assets map to one target path. No family
filenames are committed.

Three findings these fixtures exist to pin, all from that capture:

1. **There is no completion sentence.** `All photos and videos have been
   downloaded` is not emitted in this mode, so 005's primary completeness signal
   is unavailable. Completeness is exit 0 + no failure signal + a final newline.
2. **Errors arrive on stdout, interleaved with items.** Three accounts with
   expired sessions wrote `Authentication required for Account. (421)` to
   stdout, not stderr, even at `--log-level error`. A reader that assumed stdout
   held only paths would have read that as a one-item library.
3. **A listed path is not a unique key.** 6,100 lines held 6,087 unique paths;
   the duplicates were adjacent pairs of distinct assets sharing a target path,
   which the downloader resolves with a size suffix at fetch time.
