# Contract: Enumeration → `Listing`

How `icloudpd --only-print-filenames` output becomes a `Listing`. Every rule
here is transcribed from captured real output (research R1–R5), not from
documentation.

## 1. Invocation

Built by the shared argument builder so the safety test covers it:

```
icloudpd --username <u> --directory <mirror> --cookie-directory <session>
         --domain com --password-provider keyring
         --size original --live-photo-size original
         --live-photo-mov-filename-policy original
         --folder-structure "{:%Y/%m}"
         --no-progress-bar --log-level error
         --only-print-filenames
```

**Mandatory properties:**

- `--folder-structure "{:%Y/%m}"` and the live-photo policy MUST match the
  download invocation exactly. If they diverge, the listing produces paths the
  archive could never have recorded and *every* item reads as missing.
- `--log-level error` keeps stdout to paths plus genuine failures.
- No `--auto-delete`, no `--delete-after-download`, ever (Principle I); asserted
  by the argument safety test.
- `stdin` MUST be `DEVNULL` — same reasoning as the download path. An audit that
  blocks on an invisible 2FA prompt is worse than one that fails.
- Run MUST be preceded by `session_status(session_dir, username)` returning ok.

## 2. Line classification

For each line of stdout:

| Condition | Treated as |
|---|---|
| Starts with the mirror prefix | An item; strip prefix, add to `paths` |
| Anything else | A log line; scan for failure signals |

A positive prefix test, not a negative log test. Observed: **6,100 of 6,100
lines from a healthy run were items** — but a failed run put its error on
stdout, so the classifier must not assume either population dominates.

## 3. Failure signals (all set `complete = False`)

```python
_RE_AUTH_REQUIRED = r"Authentication required for Account"
_RE_ACCOUNT_LOCKED = r"Apple Account has been\s*locked|iforgot\.apple\.com"
_RE_BAD_CREDENTIALS = r"Invalid email/password combination"
_RE_MFA_REQUIRED = r"Two-(?:factor|step) authentication is required"   # reused
```

Verbatim from real output. `Authentication required for Account. (421)` was
observed on three accounts; the lock message on one.

Any unclassified line at ERROR level also sets `complete = False` — an
unrecognized failure is still a failure.

## 4. Completeness

`complete` is true only when **all** hold:

1. exit code is `0`
2. no failure signal was seen
3. the final line ended with a newline (not truncated mid-line)
4. the downloader version is in `TESTED_ICLOUDPD_VERSIONS`

There is **no completion sentence** in this mode — `All photos and videos have
been downloaded` is not emitted. Condition 1–4 together replace it.

An empty library is a legitimate `complete` listing with zero paths, provided
1–4 hold. "Zero items" and "could not list" must never collapse into one state.

## 5. Streaming

Lines are consumed as they arrive, not buffered. A 40,000-item listing takes
10–20 minutes, so a progress callback reports lines seen on the same cadence as
the download path's reporter (FR-026). Memory holds one set of ~40,000 short
strings — a few megabytes, not a concern.

## 6. Fixture

`tests/fixtures/icloudpd_streams/enumeration-sample.log` — derived from captured
`matt-public` output with filenames replaced, preserving the folder structure,
HEIC+MOV pairing, added-order month spread, and the colliding duplicate pair.
Additional fixtures cover the truncated, error-interleaved, and empty cases.
