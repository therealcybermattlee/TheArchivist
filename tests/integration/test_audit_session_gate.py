"""Integration: an audit never attempts a sign-in (006 SC-008).

An audit is meant to run weekly and largely unwatched. If it could attempt a
sign-in with unusable credentials it would feed Apple's failure counter on a
schedule — and a burst of failed attempts is precisely what locked an account
on 2026-10-27, which then took an iforgot identity check to clear.

So the credential check is local (it reads the cookie jar) and runs BEFORE the
subprocess. These tests fail if the downloader is reached at all.
"""

from __future__ import annotations

import http.cookiejar as cj
import time

import pytest
from typer.testing import CliRunner

import archivist.icloud as icloud
from archivist.cli import app

from ._pullhelp import read_meta, write_config
from tests.unit.test_session_validity import COMPLETED, HANDSHAKE_ONLY, write_jar

runner = CliRunner()

SOURCES = {"demo": {"type": "icloud", "device_folder": "Demo Cell",
                    "username": "demo@example.com"}}


def test_dead_session_makes_no_subprocess_call(cfg, tmp_path, monkeypatch):
    path = write_config(tmp_path, cfg, SOURCES)
    # A failed sign-in leaves the handshake cookies behind, so the jar EXISTS.
    write_jar(cfg.icloud_session_dir, "demo@example.com", HANDSHAKE_ONLY)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud, "probe_version", lambda: "1.32.3")
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("no sign-in may be attempted"))

    res = runner.invoke(app, ["audit", "--source", "demo", "--apply",
                              "--config", str(path)])
    assert res.exit_code == 1
    assert "could not verify" in res.output
    assert "never completed" in res.output
    assert read_meta(cfg, "reconcile_state:demo") is None


def test_a_neighbours_valid_session_does_not_satisfy_this_source(cfg, tmp_path,
                                                                 monkeypatch):
    """All accounts share one cookie directory."""
    path = write_config(tmp_path, cfg, SOURCES)
    write_jar(cfg.icloud_session_dir, "someone-else@example.com", COMPLETED)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud, "probe_version", lambda: "1.32.3")
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("no sign-in may be attempted"))

    res = runner.invoke(app, ["audit", "--source", "demo", "--config", str(path)])
    assert res.exit_code == 1
    assert "no session file for demo@example.com" in res.output


def test_enumerate_library_itself_refuses_before_popen(cfg, tmp_path, monkeypatch):
    """Belt and braces: the refusal lives in the library call, not only the CLI."""
    write_jar(cfg.icloud_session_dir, "demo@example.com", HANDSHAKE_ONLY)
    monkeypatch.setattr(icloud, "icloudpd_available", lambda: True)
    monkeypatch.setattr(icloud.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("no sign-in may be attempted"))
    listing = icloud.enumerate_library("demo@example.com", tmp_path / "m",
                                       cfg.icloud_session_dir, version="1.32.3")
    assert not listing.complete
    assert any("never completed" in n for n in listing.notes)
