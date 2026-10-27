"""Unit tests: a ROUTINE_BOUNDED run bounds enumeration (005 FR-019/FR-021).

`--recent N` truncates icloudpd's iterator with itertools.islice, so it bounds
the WALK, not just the downloads (research R1). `--skip-created-before` is the
opposite: a per-item filter that never terminates the loop. Both are needed —
the count bounds the scan, the date stops a pruned mirror re-fetching content
that is already archived.
"""

from archivist.icloud import build_download_cmd


def cmd(**kw):
    from pathlib import Path
    return build_download_cmd("me@example.com", Path("/m"), Path("/s"), **kw)


def test_bounded_run_carries_both_bounds():
    c = cmd(recent=500, since="2026-09-19")
    assert c[c.index("--recent") + 1] == "500"
    assert c[c.index("--skip-created-before") + 1] == "2026-09-19"


def test_the_count_bound_is_what_stops_the_walk():
    """A date filter alone is what made every routine run walk the library."""
    assert "--recent" not in cmd(since="2026-09-19")
    assert "--recent" in cmd(recent=500, since="2026-09-19")


def test_configured_bound_is_passed_verbatim():
    for bound in (50, 500, 1500):
        assert cmd(recent=bound)[cmd(recent=bound).index("--recent") + 1] == str(bound)


def test_until_found_is_still_available_as_an_explicit_flag():
    """Retained for deliberate use; unusable as the routine primitive because
    a pruned mirror never accumulates the consecutive-found counter."""
    c = cmd(until_found=100)
    assert c[c.index("--until-found") + 1] == "100"
