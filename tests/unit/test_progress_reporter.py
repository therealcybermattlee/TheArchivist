"""Unit tests: the throttled progress reporter (005 operability).

The first version averaged over the whole run, so a one-off startup cost — an
exiftool batch across every file — was folded into the per-item rate. On a real
33k-file sweep it displayed "6/s, ~86m left" while the loop was running at
68/s with ~7 minutes to go. That number was read as a measurement and reported
to the operator as one, twice. A progress display that lies is worse than none:
it converts "I don't know" into a confident wrong answer.
"""

from __future__ import annotations

import re

import pytest

from archivist.cli import _progress_reporter


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock."""
    import archivist.cli as cli_mod
    state = {"t": 1000.0}
    monkeypatch.setattr(cli_mod.time, "monotonic", lambda: state["t"])
    return state


def lines(capsys):
    err = capsys.readouterr().err
    return [l.strip() for l in err.splitlines() if l.strip()]


def parse(line: str) -> tuple[int, float]:
    m = re.search(r"(\d+)/(\d+) \(([\d.]+)/s", line)
    return int(m.group(1)), float(m.group(3))


def test_throttles_to_one_line_per_interval(clock, capsys):
    report = _progress_reporter("planning", every=5.0)
    for i in range(1, 11):
        clock["t"] += 1.0
        report(i, 100)
    out = lines(capsys)
    assert len(out) == 2          # at t+5 and t+10, not ten lines


def test_final_item_always_reports(clock, capsys):
    report = _progress_reporter("planning", every=5.0)
    report(1, 2)
    clock["t"] += 0.1
    report(2, 2)                  # under the throttle, but it is the last
    assert len(lines(capsys)) == 2


def test_a_slow_start_does_not_depress_the_reported_rate(clock, capsys):
    """THE regression. A long stall before the loop must not be averaged in."""
    report = _progress_reporter("planning", every=5.0, window=30.0)
    clock["t"] += 180.0           # 3 minutes of startup before item 1
    report(1, 33116)
    for _ in range(8):            # then a steady 68/s
        clock["t"] += 5.0
        report_i = 1 + int((clock["t"] - 1180.0) * 68)
        report(report_i, 33116)
    _, rate = parse(lines(capsys)[-1])
    assert 60 <= rate <= 76, rate  # the real loop rate, not 1/3rd of it


def test_rate_tracks_a_slowdown(clock, capsys):
    report = _progress_reporter("planning", every=5.0, window=30.0)
    i = 0
    for _ in range(10):           # fast phase
        clock["t"] += 5.0
        i += 500
        report(i, 100000)
    for _ in range(8):            # then it slows to a crawl
        clock["t"] += 5.0
        i += 10
        report(i, 100000)
    _, rate = parse(lines(capsys)[-1])
    assert rate < 10, rate        # reflects now, not the fast start


def test_first_line_admits_it_cannot_estimate(clock, capsys):
    report = _progress_reporter("planning", every=5.0)
    report(1, 100)
    assert "estimating" in lines(capsys)[0]


def test_eta_is_derived_from_the_windowed_rate(clock, capsys):
    report = _progress_reporter("planning", every=5.0, window=30.0)
    report(0, 1000)
    clock["t"] += 10.0
    report(100, 1000)             # 10/s, 900 remaining -> 90s -> ~2m
    assert "~2m left" in lines(capsys)[-1]
