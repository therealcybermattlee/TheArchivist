"""Unit tests: the pre-flight session check (005 FR-002, contract case 23).

Purpose is failing FAST, not proving authentication. A cookie file can sit on
disk long expired; genuine credential failure is signalled by icloudpd's
non-zero exit, which build_proof refuses on. What this buys is refusing in
seconds instead of after a full library enumeration.
"""

import archivist.icloud as icloud


def test_absent_session_dir_refuses_without_invoking(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
                            AssertionError("downloader must not be invoked")))
    proof = icloud.download("me@example.com", tmp_path / "mirror",
                            tmp_path / "missing-session", version="1.32.3")
    assert not proof.parser_confident
    assert not proof.session_present_before
    assert any("session artifact" in n for n in proof.notes)
    assert called == []


def test_empty_session_dir_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    session = tmp_path / "session"
    session.mkdir()
    proof = icloud.download("me@example.com", tmp_path / "mirror", session,
                            version="1.32.3")
    assert not proof.session_present_before
    assert not proof.parser_confident


def test_dotfiles_do_not_count_as_a_session(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / ".DS_Store").write_text("noise")
    assert not icloud.session_established(session)


def test_present_artifact_proceeds(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "me@example.com.cookies").write_text("cookie")
    assert icloud.session_established(session)


def test_preflight_refusal_does_not_create_the_mirror(tmp_path, monkeypatch):
    """A refused pre-flight must not have side effects on the work volume."""
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    mirror = tmp_path / "mirror"
    icloud.download("me@example.com", mirror, tmp_path / "nope", version="1.32.3")
    assert not mirror.exists()
