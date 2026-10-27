"""Unit tests: parsing icloudpd's output stream into a CoverageProof (005).

Contract cases 1, 2, 6 of contracts/coverage-proof.md §6. Fixtures live in
tests/fixtures/icloudpd_streams/ — see the README there for provenance.
"""

from pathlib import Path

import pytest

from archivist.icloud import StreamTally, build_proof, parse_lines

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "icloudpd_streams"


def stream(name: str) -> list[str]:
    return FIXTURES.joinpath(name).read_text(encoding="utf-8").splitlines()


# --- case 1: completion present, clean exit --------------------------------

def test_complete_unbounded_is_confirmed():
    proof = parse_lines(stream("complete-unbounded.log"))
    assert proof.enumeration_complete
    assert proof.parser_confident
    assert proof.notes == ()


def test_counts_are_tallied():
    proof = parse_lines(stream("complete-unbounded.log"))
    assert proof.downloaded == 2          # two "Downloaded" lines, not the banner
    assert proof.already_present == 1
    assert proof.reached_before_cutoff    # three skip-before lines
    assert proof.examined == 6


# --- the three signals that were wrong, pinned to real upstream wording -----
#
# Each of these once passed against invented fixtures while failing against the
# real thing. They assert the verbatim v1.32.3 format strings.

@pytest.mark.parametrize("count_str,phrase", [
    ("the first", "photo or video"),      # upstream uses this ONLY when N == 1
    ("2202", "photos and videos"),         # the ordinary multi-item case
    ("500", "photos and videos"),
    ("0", "photos and videos"),
    ("???", "photos and videos"),          # when the count is unknown
])
def test_download_preamble_is_never_an_item(count_str, phrase):
    """"Downloading %s %s %s to %s ..." is a one-off banner.

    Recognising only the N==1 wording meant every real multi-item run counted
    the banner as a download — enough, with an empty mirror, to make a healthy
    quiet source report FAILED forever.
    """
    tally = StreamTally()
    tally.feed(f"2026-09-26 13:34:43 INFO     Downloading {count_str} original "
               f"{phrase} to /work/staging/icloud/demo ...")
    assert tally.downloaded == 0


def test_per_item_downloads_are_past_tense():
    """Upstream logs "Downloaded %s" per item, not "Downloading"."""
    tally = StreamTally()
    tally.feed("2026-09-26 13:34:44 INFO     Downloaded /work/m/IMG_1820.PNG")
    assert tally.downloaded == 1


def test_present_tense_per_item_line_is_still_tolerated():
    """Older builds phrase it in the present tense; both must count."""
    tally = StreamTally()
    tally.feed("2026-09-26 13:34:44 INFO     Downloading /work/m/IMG_1820.PNG ...")
    assert tally.downloaded == 1


def test_already_exists_has_no_trailing_period():
    """Upstream format string is "%s already exists" — requiring a period made
    already_present permanently 0."""
    tally = StreamTally()
    tally.feed("2026-09-26 13:34:47 DEBUG    /work/m/IMG_1819.HEIC already exists")
    assert tally.already_present == 1


def test_quiet_source_reports_zero_downloads():
    """The case F1 broke: nothing new, so nothing may look like a download."""
    proof = parse_lines(stream("quiet-source.log"))
    assert proof.downloaded == 0
    assert proof.enumeration_complete
    assert proof.reached_before_cutoff
    assert proof.parser_confident


# --- case 2: all three completion phrasings --------------------------------

@pytest.mark.parametrize("phrase", ["photos and videos", "photos", "videos"])
def test_every_completion_phrasing_is_recognised(phrase):
    proof = parse_lines([f"2026-09-26 13:00:00 INFO     All {phrase} have been downloaded"])
    assert proof.enumeration_complete
    assert proof.parser_confident


# --- signal discrimination -------------------------------------------------

def test_bounded_run_that_cleared_the_window():
    proof = parse_lines(stream("complete-bounded.log"))
    assert proof.enumeration_complete
    assert proof.reached_before_cutoff
    assert proof.already_present == 1


def test_bounded_run_that_did_not_clear_the_window():
    """Completion alone does NOT prove a bounded scan covered its window.

    Under --recent the iterator is truncated by islice, so the loop still ends
    normally and the completion line still appears. The skip-before-cutoff line
    is the only evidence enumeration reached past the cutoff.
    """
    proof = parse_lines(stream("bounded-window-not-cleared.log"))
    assert proof.enumeration_complete
    assert not proof.reached_before_cutoff


def test_until_found_exit_is_recognised():
    proof = parse_lines(stream("until-found-exit.log"))
    assert proof.until_found_exit
    assert not proof.enumeration_complete
    assert proof.already_present == 3
    # An until-found exit is a real completion signal, so the parser is
    # confident — but the mode is NARROW, so the decision refuses anyway.
    assert proof.parser_confident


def test_skip_after_counts_toward_examined_not_before():
    proof = parse_lines([
        "DEBUG Skipping IMG_1.HEIC, as it was created 2027-01-01 00:00:00-05:00, "
        "after 2026-09-19 00:00:00-04:00.",
        "INFO     All photos and videos have been downloaded",
    ])
    assert not proof.reached_before_cutoff
    assert proof.examined == 1


# --- case 6: truncation ----------------------------------------------------

def test_truncated_stream_fails_closed():
    proof = parse_lines(stream("truncated-midline.log"), truncated=True)
    assert not proof.parser_confident
    assert any("mid-line" in n for n in proof.notes)


def test_build_proof_reports_every_reason_not_just_the_first():
    proof = build_proof(StreamTally(), exit_code=1, session_present_before=False,
                        version="9.9.9", truncated=True)
    text = proof.note_text()
    assert "session artifact" in text
    assert "not a version this parser" in text
    assert "exited 1" in text
    assert "mid-line" in text
    assert "no completion signal" in text


def test_both_phrasings_for_one_item_count_once():
    """icloudpd logs the present tense on start and the past tense on finish.

    Summing them reported 66,224 downloads for a real 33,124-file sweep —
    exactly 2x. `downloaded` feeds the §4.3 decision, so an inflated count is
    not merely cosmetic.
    """
    tally = StreamTally()
    tally.feed("INFO     Downloading /work/m/IMG_1820.PNG ...")
    tally.feed("INFO     Downloaded /work/m/IMG_1820.PNG")
    assert tally.downloaded == 1


def test_past_tense_alone_counts():
    tally = StreamTally()
    for n in range(3):
        tally.feed(f"INFO     Downloaded /work/m/IMG_{n}.PNG")
    assert tally.downloaded == 3


def test_present_tense_alone_is_the_fallback():
    tally = StreamTally()
    for n in range(3):
        tally.feed(f"INFO     Downloading /work/m/IMG_{n}.PNG ...")
    assert tally.downloaded == 3
