"""Unit tests: a two-factor prompt must fail fast, never hang (regression).

The coverage-proof work changed `download()` from `subprocess.run` (which
inherits the terminal) to a captured `Popen`. That silently broke interactive
re-authentication: when the session expired, icloudpd's "Please enter
two-factor authentication code: " prompt went into our pipe instead of the
operator's terminal, while stdin stayed connected — so it waited forever for a
code nobody could see it asking for. Apple showed a sign-in; the tool showed
nothing.

Detection strings are verbatim from upstream v1.32.3 `authentication.py`.
"""

from __future__ import annotations

import subprocess

import pytest

import archivist.icloud as icloud
from archivist.icloud import StreamTally, parse_lines

# These tests need a session that passes the per-account pre-flight, so that
# what they exercise is the MFA path and not the pre-flight refusal.
from .test_session_validity import COMPLETED, write_jar


@pytest.mark.parametrize("line", [
    "2026-10-26 09:00:01 INFO     Two-factor authentication is required (2fa)",
    "2026-10-26 09:00:01 INFO     Two-step authentication is required (2sa)",
])
def test_mfa_requirement_is_recognised(line):
    tally = StreamTally()
    tally.feed(line)
    assert tally.mfa_required


def test_mfa_fails_closed_with_an_actionable_note():
    proof = parse_lines([
        "INFO     Two-factor authentication is required (2fa)",
    ])
    assert not proof.parser_confident
    assert any("two-factor code" in n for n in proof.notes)
    assert any("re-authenticate" in n for n in proof.notes)


def test_mfa_note_replaces_the_generic_completion_complaint():
    """The operator should be told to sign in, not that a signal was missing."""
    proof = parse_lines(["INFO     Two-factor authentication is required (2fa)"])
    assert not any("no completion signal" in n for n in proof.notes)


def test_a_normal_run_does_not_trip_the_detector():
    proof = parse_lines([
        "INFO     Downloaded /work/m/IMG_1.HEIC",
        "INFO     All photos and videos have been downloaded",
    ])
    assert proof.parser_confident


def test_stdin_is_never_inherited(tmp_path, monkeypatch):
    """The structural guard: even if the wording changes, it cannot block.

    An inherited stdin lets icloudpd wait indefinitely on a prompt the operator
    cannot see. DEVNULL turns that into an immediate EOF.
    """
    session = tmp_path / "s"
    write_jar(session, "me@example.com", COMPLETED)
    seen = {}

    class FakeProc:
        returncode = 0
        stdout = iter(["INFO     All photos and videos have been downloaded\n"])

        def wait(self): return 0
        def kill(self): pass

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return FakeProc()

    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen", fake_popen)
    icloud.download("me@example.com", tmp_path / "m", session, version="1.32.3")
    assert seen["stdin"] is subprocess.DEVNULL


def test_the_downloader_is_killed_once_a_code_is_wanted(tmp_path, monkeypatch):
    """Don't drain the rest of the stream waiting for an EOF that may not come."""
    session = tmp_path / "s"
    write_jar(session, "me@example.com", COMPLETED)
    killed = []

    class FakeProc:
        returncode = 0

        def __init__(self):
            self.stdout = iter([
                "INFO     Two-factor authentication is required (2fa)\n",
                "Please enter two-factor authentication code: \n",
            ])

        def wait(self): return 0
        def kill(self): killed.append(True)

    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    proof = icloud.download("me@example.com", tmp_path / "m", session,
                            version="1.32.3")
    assert killed == [True]
    assert not proof.parser_confident
