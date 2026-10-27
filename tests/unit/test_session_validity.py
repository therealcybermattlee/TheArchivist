"""Unit tests: per-account session validity (follow-up to 005).

The bug these pin down, observed live on 2026-10-27: Apple locked an account,
icloudpd logged the lockout and exited 0, and `archivist auth` printed
"iCloud session established" in green. Two separate defects let that through:

  1. the check asked "does the shared cookie directory contain any file?",
     which is true whenever ANY of the four accounts has ever signed in; and
  2. a FAILED sign-in still rewrites that account's jar with the pre-auth
     handshake cookies, so even a per-account presence check would say yes.

The fix keys on cookies Apple writes only after a sign-in completes, per
account, by reading the jar locally -- never by asking Apple, because the
account most in need of diagnosis is the one that is locked out.
"""

import http.cookiejar as cj
import time

import pytest

import archivist.icloud as icloud

#: What a failed sign-in leaves behind -- transcribed from the real jar of the
#: locked account (7 cookies, none of them proof of anything).
HANDSHAKE_ONLY = ("aasp", "acn01", "dslang", "site", "X-APPLE-WEBAUTH-HSA-TRUST")
#: What a completed sign-in leaves behind, in addition to the handshake.
COMPLETED = HANDSHAKE_ONLY + ("X-APPLE-WEBAUTH-TOKEN", "X-APPLE-WEBAUTH-USER",
                              "X-APPLE-DS-WEB-SESSION-TOKEN")


def _cookie(name: str, expires):
    return cj.Cookie(
        version=0, name=name, value="redacted", port=None, port_specified=False,
        domain=".icloud.com", domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True, secure=True, expires=expires,
        discard=False, comment=None, comment_url=None, rest={},
    )


def write_jar(session_dir, username, names, expires=None):
    """Write a cookie jar the way icloudpd would, for `username`."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / icloud.session_file_for(username)
    jar = cj.LWPCookieJar(str(path))
    exp = time.time() + 86_400 if expires is None else expires
    for n in names:
        jar.set_cookie(_cookie(n, exp))
    jar.save(ignore_discard=True, ignore_expires=True)
    return path


# --- icloudpd's filename rule ----------------------------------------------

@pytest.mark.parametrize("username,expected", [
    ("first.last@example.com", "firstlastexamplecom"),  # dots and @ dropped
    ("a@b.co", "abco"),                                  # shortest realistic
    ("has_underscore@x.io", "has_underscorexio"),        # \w keeps underscores
    ("plus+tag@mail.example", "plustagmailexample"),     # + dropped
    ("MixedCase@Example.COM", "MixedCaseExampleCOM"),    # case preserved
])
def test_filename_rule_matches_icloudpd(username, expected):
    """Addresses here are synthetic; the rule was checked against the real
    cookie jars on the work volume, which are not reproduced in a public repo."""
    assert icloud.session_file_for(username) == expected


# --- the live failure ------------------------------------------------------

def test_handshake_only_jar_is_not_a_session(tmp_path):
    """The locked-account case: a jar exists, but no sign-in ever completed."""
    write_jar(tmp_path, "kat@example.com", HANDSHAKE_ONLY)
    ok, why = icloud.session_status(tmp_path, "kat@example.com")
    assert not ok
    assert "never completed" in why
    assert "kat@example.com" in why


def test_completed_signin_is_a_session(tmp_path):
    write_jar(tmp_path, "kat@example.com", COMPLETED)
    ok, why = icloud.session_status(tmp_path, "kat@example.com")
    assert ok, why


def test_one_accounts_session_is_not_anothers(tmp_path):
    """Accounts share a cookie directory; a neighbour's login proves nothing.

    This is the defect that made the pre-flight unfailable in practice.
    """
    write_jar(tmp_path, "healthy@example.com", COMPLETED)
    assert icloud.session_status(tmp_path, "healthy@example.com")[0]
    ok, why = icloud.session_status(tmp_path, "broken@example.com")
    assert not ok
    assert "no session file for broken@example.com" in why


def test_expired_proof_cookie_refuses(tmp_path):
    write_jar(tmp_path, "old@example.com", COMPLETED, expires=time.time() - 10)
    ok, why = icloud.session_status(tmp_path, "old@example.com")
    assert not ok
    assert "expired" in why


def test_unreadable_jar_refuses(tmp_path):
    (tmp_path / icloud.session_file_for("x@example.com")).write_text("garbage")
    ok, why = icloud.session_status(tmp_path, "x@example.com")
    assert not ok


# --- auth may not claim success it cannot prove ----------------------------

def test_auth_refuses_to_claim_success_on_a_failed_signin(tmp_path, monkeypatch):
    """icloudpd exits 0 on a locked account. That must not read as success."""
    write_jar(tmp_path, "locked@example.com", HANDSHAKE_ONLY)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0})())
    with pytest.raises(icloud.ICloudError) as exc:
        icloud.auth("locked@example.com", tmp_path)
    assert "did not complete" in str(exc.value)
    assert "iforgot.apple.com" in str(exc.value)


def test_auth_accepts_a_completed_signin(tmp_path, monkeypatch):
    write_jar(tmp_path, "good@example.com", COMPLETED)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0})())
    assert icloud.auth("good@example.com", tmp_path) == 0


# --- pre-flight ------------------------------------------------------------

def test_download_preflight_is_per_account(tmp_path, monkeypatch):
    """A neighbour's good session must not let a dead account start a run."""
    session = tmp_path / "session"
    write_jar(session, "healthy@example.com", COMPLETED)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("downloader must not run"))
    proof = icloud.download("broken@example.com", tmp_path / "mirror", session,
                            version="1.32.3")
    assert not proof.parser_confident
    assert not proof.session_present_before
    assert "broken@example.com" in proof.note_text()


def test_preflight_refusal_names_the_reason(tmp_path, monkeypatch):
    session = tmp_path / "session"
    write_jar(session, "locked@example.com", HANDSHAKE_ONLY)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("downloader must not run"))
    proof = icloud.download("locked@example.com", tmp_path / "mirror", session,
                            version="1.32.3")
    assert "never completed" in proof.note_text()
    assert "session artifact" in proof.note_text()   # legacy substring kept
