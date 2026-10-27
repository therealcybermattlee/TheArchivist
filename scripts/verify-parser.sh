#!/usr/bin/env bash
# Validate the 005 coverage parser against REAL icloudpd output.
#
# Every automated pull test mocks the downloader, so the parser is only ever
# checked against fixtures. Those fixtures were once written from guessed
# wording and 272 tests passed over a parser that could not read real output
# (see tests/fixtures/icloudpd_streams/README.md). This closes that loop.
#
# Completely read-only: icloudpd runs with its own --dry-run, so nothing is
# downloaded, nothing is written to the mirror, and nothing in iCloud is
# touched. No --apply exists here to give.
#
# Usage:  scripts/verify-parser.sh <source-key> [item-count]
set -euo pipefail

SOURCE="${1:?usage: verify-parser.sh <source-key> [item-count]}"
COUNT="${2:-25}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${TMPDIR:-/tmp}/icloudpd-real-${SOURCE}.log"

read -r USERNAME SESSION < <(
  cd "$REPO" && python3 -c "
from archivist.config import load_config
c = load_config('config.yaml')
s = c.sources['$SOURCE']
assert s.type == 'icloud', f\"'$SOURCE' is type {s.type}, not icloud\"
print(s.username, c.icloud_session_dir)
"
)

echo "Probing $SOURCE ($USERNAME), $COUNT most recent items, icloudpd --dry-run."
echo "Nothing is downloaded or modified. Capturing to $LOG"
echo

icloudpd --username "$USERNAME" \
         --directory "${TMPDIR:-/tmp}/icloudpd-probe-discard" \
         --cookie-directory "$SESSION" \
         --domain com \
         --password-provider keyring \
         --log-level debug \
         --no-progress-bar \
         --dry-run \
         --recent "$COUNT" 2>&1 | tee "$LOG"

echo
echo "=== what the parser made of that ==="
cd "$REPO" && python3 -c "
import sys
from archivist.icloud import parse_lines, probe_version
lines = open('$LOG', encoding='utf-8', errors='replace').read().splitlines()
p = parse_lines(lines, exit_code=0, session_present_before=True,
                version=probe_version())
print(f'  icloudpd version      {probe_version()}')
print(f'  lines captured        {len(lines)}')
print(f'  enumeration_complete  {p.enumeration_complete}')
print(f'  reached_before_cutoff {p.reached_before_cutoff}')
print(f'  examined              {p.examined}')
print(f'  downloaded            {p.downloaded}')
print(f'  already_present       {p.already_present}')
print(f'  parser_confident      {p.parser_confident}')
if p.notes:
    print('  notes:')
    for n in p.notes:
        print(f'    - {n}')
print()
bad = []
if not p.enumeration_complete:
    bad.append('no completion signal recognised')
if p.examined == 0:
    bad.append('examined 0 — no per-item signal recognised at all')
if p.downloaded and '--dry-run' in ' '.join(sys.argv):
    pass
if bad:
    print('PARSER MISMATCH — do not trust coverage decisions until fixed:')
    for b in bad:
        print(f'  * {b}')
    print(f'\\n  Raw output is at $LOG — the wording has drifted from')
    print('  tests/fixtures/icloudpd_streams/. Update the fixtures AND the')
    print('  regexes in src/archivist/icloud.py together.')
    raise SystemExit(1)
print('PARSER OK against real output for this source.')
"
