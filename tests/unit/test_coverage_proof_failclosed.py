"""Unit tests: the fail-closed rules (005, contracts §3.1, cases 3/4/5).

Failing closed is the deliberate failure direction of this whole feature: an
upstream rewording must degrade to "watermarks stop advancing and the run says
why", never to a silent advance.
"""

from pathlib import Path

from archivist.icloud import TESTED_ICLOUDPD_VERSIONS, StreamTally, parse_lines

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "icloudpd_streams"


def stream(name: str) -> list[str]:
    return FIXTURES.joinpath(name).read_text(encoding="utf-8").splitlines()


# --- case 3: no completion signal, clean exit ------------------------------

def test_no_completion_signal_fails_closed():
    proof = parse_lines(["DEBUG Authenticating...", "DEBUG nothing else happened"])
    assert not proof.parser_confident
    assert any("no completion signal" in n for n in proof.notes)


def test_auth_failure_stream_fails_closed():
    proof = parse_lines(stream("auth-failure.log"), exit_code=1)
    assert not proof.parser_confident
    assert not proof.enumeration_complete


# --- case 4: non-zero exit even WITH a completion line ---------------------

def test_nonzero_exit_overrides_a_completion_line():
    proof = parse_lines(
        ["INFO     All photos and videos have been downloaded"], exit_code=1)
    assert proof.enumeration_complete       # the line was genuinely seen
    assert not proof.parser_confident       # but the process still failed
    assert any("exited 1" in n for n in proof.notes)


# --- case 5: untested downloader version -----------------------------------

def test_untested_version_fails_closed():
    proof = parse_lines(
        ["INFO     All photos and videos have been downloaded"], version="2.0.0")
    assert not proof.parser_confident
    assert any("not a version this parser" in n for n in proof.notes)


def test_unknown_version_fails_closed():
    proof = parse_lines(
        ["INFO     All photos and videos have been downloaded"], version=None)
    assert not proof.parser_confident
    assert any("could not be determined" in n for n in proof.notes)


def test_tested_version_is_accepted():
    for v in TESTED_ICLOUDPD_VERSIONS:
        proof = parse_lines(
            ["INFO     All photos and videos have been downloaded"], version=v)
        assert proof.parser_confident, v


# --- default proof ---------------------------------------------------------

def test_default_proof_is_never_confident():
    """A CoverageProof nobody filled in must not authorise anything."""
    from archivist.icloud import CoverageProof
    assert not CoverageProof().parser_confident
    assert not CoverageProof().enumeration_complete
