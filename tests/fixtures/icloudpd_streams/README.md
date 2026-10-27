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
