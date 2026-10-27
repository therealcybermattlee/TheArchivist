"""The Archivist CLI (typer).

Phase 0: `status` and `init-volumes` are functional. Ingest/pull/dedupe are
stubs that announce their target phase so the surface is visible end-to-end.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .catalog import Catalog
from .config import Config, ConfigError, load_config, small_scan_bound_warnings
from .guard import GuardError, check_volumes, init_volume, require_volumes

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="The Archivist — safe, on-demand media archival for the Lee Family library.",
)

# Shared --config option.
ConfigOpt = typer.Option(
    None, "--config", "-c", help="Path to config.yaml (default: ./config.yaml or $ARCHIVIST_CONFIG)."
)


def _load(config_path: Optional[str]) -> Config:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"Config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)


def _ok(s: bool) -> str:
    return typer.style("OK", fg=typer.colors.GREEN) if s else typer.style("FAIL", fg=typer.colors.RED)


@app.command()
def status(config: Optional[str] = ConfigOpt) -> None:
    """Show volume guard status and catalog statistics."""
    cfg = _load(config)
    typer.echo(f"The Archivist v{__version__}")
    typer.echo(f"config:       {cfg.path}")
    typer.echo(f"archive_root: {cfg.archive_root}")
    typer.echo(f"work_root:    {cfg.work_root}  (mount)")
    typer.echo(f"work_dir:     {cfg.work_base}  (staging/drops/logs/catalog)")
    typer.echo(f"timezone:     {cfg.default_timezone}")
    typer.echo("")

    typer.secho("Volumes", bold=True)
    all_ok = True
    for s in check_volumes(cfg):
        all_ok = all_ok and s.ok
        sid = f" id={s.sentinel_id}" if s.sentinel_id else ""
        typer.echo(
            f"  {s.label:<12} {_ok(s.ok)}  {s.path}\n"
            f"               mounted={s.exists} dir={s.is_dir} "
            f"writable={s.writable} sentinel={s.sentinel}{sid}"
        )
    if not all_ok:
        typer.secho(
            "  -> Mutating commands will refuse to run. "
            "Mount the shares and run `archivist init-volumes`.",
            fg=typer.colors.YELLOW,
        )
    typer.echo("")

    typer.secho("Catalog", bold=True)
    cat = Catalog(cfg.catalog_db)
    st = cat.stats()
    typer.echo(f"  db:            {cfg.catalog_db} ({'present' if cat.exists() else 'not created yet'})")
    typer.echo(f"  schema:        v{st.schema_version}")
    typer.echo(f"  total assets:  {st.total}")
    if st.by_confidence:
        typer.echo("  by confidence: " + ", ".join(f"{k}={v}" for k, v in sorted(st.by_confidence.items())))
    if st.by_source:
        typer.echo("  by source:     " + ", ".join(f"{k}={v}" for k, v in sorted(st.by_source.items())))

    if cfg.work_base.is_dir():
        from .doctor import WORK_BUDGET_BYTES, _dir_usage
        used = _dir_usage(cfg.work_base)
        over = used > WORK_BUDGET_BYTES
        line = (f"  work storage:  {used / 1024**3:.1f} GB used "
                f"(~{WORK_BUDGET_BYTES / 1024**3:.0f} GB budget)")
        typer.secho(line, fg=typer.colors.YELLOW if over else None)
        if over:
            typer.secho("    -> over budget: `archivist prune-staging` reclaims verified staging.",
                        fg=typer.colors.YELLOW)

    if cat.exists() and st.total:
        typer.echo("")
        typer.secho("Location coverage", bold=True)
        cov = cat.location_coverage()
        o = cov["overall"]
        typer.echo(
            f"  overall:  located {o.get('present', 0)}, absent {o.get('absent', 0)}, "
            f"rejected {o.get('rejected', 0)}, unexamined {o.get('unexamined', 0)}"
        )
        if o.get("unexamined"):
            typer.secho("    -> run `archivist scan-locations` to examine the rest.",
                        fg=typer.colors.YELLOW)
        for label, key in (("by year", "by_year"), ("by source", "by_source")):
            buckets = cov[key]
            if buckets:
                parts = [
                    f"{b}: {v.get('present', 0)}/{sum(v.values())}"
                    for b, v in sorted(buckets.items())
                ]
                typer.echo(f"  {label} (located/total): " + ", ".join(parts))


@app.command()
def doctor(config: Optional[str] = ConfigOpt) -> None:
    """Environment health check for THIS host (read-only, provisioning-safe).

    Verifies config paths, volumes, external tools, HEIC support, secure
    keyring, timezone, and working-storage budget. Exit 0 only when every
    required check passes.
    """
    from .doctor import run_checks

    cfg = _load(config)
    checks = run_checks(cfg)
    typer.secho("Doctor", bold=True)
    failed_required = False
    for c in checks:
        tag = "required" if c.required else "info"
        typer.echo(f"  {_ok(c.ok)}  {c.name:<14} [{tag:<8}] {c.detail}")
        if not c.ok and c.remedy:
            typer.secho(f"        -> {c.remedy}", fg=typer.colors.YELLOW)
        if c.required and not c.ok:
            failed_required = True
    typer.echo("")
    if failed_required:
        typer.secho("Doctor: required checks FAILED — fix the items above.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)
    typer.secho("Doctor: all required checks passed.", fg=typer.colors.GREEN, bold=True)


@app.command("init-volumes")
def init_volumes(config: Optional[str] = ConfigOpt) -> None:
    """Create `.archivist-volume-id` sentinels on the archive and work mounts.

    Run once, after the correct shares are mounted. Writes only the tiny
    sentinel id files (never any media).
    """
    cfg = _load(config)
    for label, path in (("archive_root", cfg.archive_root), ("work_root", cfg.work_root)):
        if not path.is_dir():
            typer.secho(f"  {label}: {path} is not a mounted directory — skipping.", fg=typer.colors.RED)
            continue
        try:
            vid, created = init_volume(path)
        except OSError as exc:
            typer.secho(f"  {label}: {path} — could not write sentinel: {exc}", fg=typer.colors.RED)
            continue
        verb = "created" if created else "already present"
        typer.secho(f"  {label}: sentinel {verb} ({vid})", fg=typer.colors.GREEN)

    # Initialize the catalog DB + working subdirs while we're here.
    if cfg.work_root.is_dir():
        for d in (cfg.staging_dir, cfg.drops_dir, cfg.logs_dir, cfg.catalog_dir):
            d.mkdir(parents=True, exist_ok=True)
        Catalog(cfg.catalog_db).init_db()
        typer.secho(f"  catalog: initialized at {cfg.catalog_db}", fg=typer.colors.GREEN)


def _require(cfg: Config) -> None:
    from .config import validate_roots

    root_errors = validate_roots(cfg)
    if root_errors:
        typer.secho("Refusing to run — configuration invalid for this host:",
                    fg=typer.colors.RED, err=True)
        for e in root_errors:
            typer.secho(f"  - {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        require_volumes(cfg)
    except GuardError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)


@app.command("scan-archive")
def scan_archive(
    path: Optional[Path] = typer.Argument(
        None, help="Subpath to scan (default: archive_root). Must be inside archive_root."
    ),
    full_hash: bool = typer.Option(False, "--full-hash", help="Also compute full sha256 of every file (slow; reads all bytes)."),
    no_hash: bool = typer.Option(False, "--no-hash", help="Skip all hashing (metadata-only pass)."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Index at most N files (for testing)."),
    no_write: bool = typer.Option(False, "--no-write", help="Compute but do not write to the catalog."),
    show: int = typer.Option(10, "--show", help="Print the first N resolved rows."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """[Phase 1] Read-only index of the existing archive into the catalog.

    Reads files and writes ONLY to the catalog DB — never to the archive.
    """
    from .catalog import Catalog
    from .scanner import scan

    cfg = _load(config)
    root = (path or cfg.archive_root).resolve()
    arc = cfg.archive_root.resolve()
    if root != arc and arc not in root.parents:
        typer.secho(f"Refusing: {root} is not inside archive_root ({arc}).", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if not root.is_dir():
        typer.secho(f"Not a directory: {root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    hash_mode = "none" if no_hash else ("full+quick" if full_hash else "quick")
    typer.echo(f"Scanning {root}")
    typer.echo(f"  hashing={hash_mode}  write={'off' if no_write else 'on'}"
               + (f"  limit={limit}" if limit else ""))

    def _progress(i: int, p: Path) -> None:
        if i % 200 == 0:
            typer.echo(f"  ...{i} files", err=True)

    cat = Catalog(cfg.catalog_db)
    result = scan(
        root, cat, cfg.default_timezone,
        do_quick=not no_hash, do_full=full_hash and not no_hash, do_phash=not no_hash,
        limit=limit, write=not no_write, progress=_progress,
    )

    typer.echo("")
    typer.secho(f"Indexed {result.indexed} files; {len(result.errors)} errors.", bold=True)
    if result.conf_counts:
        typer.echo("  confidence: " + ", ".join(f"{k}={v}" for k, v in sorted(result.conf_counts.items())))

    for r in result.sample_rows[:show]:
        name = Path(r["archive_path"]).name
        typer.echo(
            f"  {r['capture_dt'][:10]}  [{r['confidence']:<6} {r['date_source']:<8}] "
            f"{r['mime_type'] or '?':<12} {name}"
        )
    for p, err in result.errors[:show]:
        typer.secho(f"  ERROR {p.name}: {err}", fg=typer.colors.RED)

    if result.suspect:
        typer.echo("")
        typer.secho(
            f"⚠ {len(result.suspect)} suspect file(s): media extension but non-media content "
            "(likely corrupt / failed download):",
            fg=typer.colors.YELLOW, bold=True,
        )
        for p, mime in result.suspect[:show]:
            typer.secho(f"    {p.name}  -> {mime}", fg=typer.colors.YELLOW)


@app.command("scan-locations")
def scan_locations(
    full: bool = typer.Option(False, "--full", help="Re-examine every item, not just never-examined ones."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Examine at most N items (for timing trials)."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Backfill capture locations for cataloged media (reads files in place).

    Reads archived files and writes ONLY to the catalog DB — never to the
    archive. Incremental and resumable: progress is committed per batch.
    """
    import time
    from .scanner import backfill_locations

    cfg = _load(config)
    _require(cfg)  # reads the archive, writes the catalog on the work drive

    cat = Catalog(cfg.catalog_db)
    if not cat.exists():
        typer.secho("No catalog yet — run `archivist scan-archive` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    typer.echo(f"Backfilling locations ({'full re-examination' if full else 'incremental'})"
               + (f", limit={limit}" if limit else ""))

    def _progress(i: int, path: str) -> None:
        if i % 200 == 0:
            typer.echo(f"  ...{i} examined", err=True)

    t0 = time.monotonic()
    try:
        res = backfill_locations(cat, full=full, limit=limit, progress=_progress)
    except Exception as exc:
        typer.secho(f"Backfill halted: {exc} (progress up to the last batch is saved)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    elapsed = time.monotonic() - t0

    typer.echo("")
    typer.secho(
        f"Examined {res.examined} items in {elapsed / 60:.1f} min: "
        f"located {res.located}, absent {res.location_absent}, rejected {res.location_rejected}.",
        bold=True,
    )
    if res.missing_files:
        typer.secho(f"  {res.missing_files} cataloged file(s) not found on disk — left unexamined.",
                    fg=typer.colors.YELLOW)
    for path, err in res.errors[:10]:
        typer.secho(f"  ERROR {Path(path).name}: {err}", fg=typer.colors.RED)


@app.command("export-map")
def export_map(
    year: Optional[str] = typer.Option(None, "--year", help="Only items from this capture year (YYYY)."),
    source: Optional[str] = typer.Option(None, "--source", help="Only items from this source label."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output .kmz path (default: exports dir, timestamped)."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Export located items as a Google Earth .kmz (clickable photo pins).

    Reads archive files for thumbnails; writes ONLY the .kmz (and its temp
    thumbnails) on the work drive. Archive and catalog are never modified.
    """
    import tempfile
    from datetime import datetime
    from . import mapexport

    cfg = _load(config)
    _require(cfg)  # reads the archive, writes to the work drive

    cat = Catalog(cfg.catalog_db)
    if not cat.exists():
        typer.secho("No catalog yet — run `archivist scan-archive` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    exports_dir = cfg.work_base / "exports"
    out_path = (out or exports_dir / f"map-{datetime.now().strftime('%Y%m%d-%H%M%S')}.kmz")

    def _progress(i: int, path: str) -> None:
        if i % 100 == 0:
            typer.echo(f"  ...{i} thumbnails", err=True)

    exports_dir.mkdir(parents=True, exist_ok=True)
    conn = cat.connect()
    try:
        with tempfile.TemporaryDirectory(dir=str(exports_dir)) as td:
            res = mapexport.export_kmz(conn, out_path, Path(td),
                                       year=year, source=source, progress=_progress)
    finally:
        conn.close()

    if not res.exported:
        typer.secho("No located items match — nothing to export. "
                    "(Run `archivist scan-locations` first?)", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    size_mb = out_path.stat().st_size / 1048576
    typer.secho(f"Exported {res.exported} located items -> {out_path} ({size_mb:.1f} MB)",
                fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  thumbnails: {res.thumbs_ok} ok, {len(res.thumb_failures)} failed"
               " (failed items still plotted, without preview)" if res.thumb_failures
               else f"  thumbnails: {res.thumbs_ok} ok")
    for path, why in res.thumb_failures[:10]:
        typer.secho(f"    no preview {Path(path).name}: {why}", fg=typer.colors.YELLOW)
    typer.echo("  Open the .kmz in Google Earth desktop; click a pin to see the photo.")


def _gb(n: int) -> str:
    return f"{n / 1073741824:.2f} GB"


def _progress_reporter(label: str, *, every: float = 5.0, window: float = 30.0):
    """A throttled progress line reporting a WINDOWED rate, not a cumulative one.

    The first version averaged over the whole run, which folded a one-off
    startup cost (an exiftool batch across every file) into the per-item rate.
    On a 33k-file sweep that reported 6/s and "~86m left" while the loop was
    actually running at ~68/s with ~7 minutes to go — a number misleading
    enough that it was reported to the operator as measurement twice.
    A trailing window tracks what the loop is doing now.
    """
    state: dict = {"last": 0.0, "samples": []}

    def report(i: int, total: int, item=None) -> None:
        now = time.monotonic()
        final = (i == total)
        if not final and now - state["last"] < every:
            return
        state["last"] = now
        samples = state["samples"]
        samples.append((now, i))
        while len(samples) > 1 and now - samples[0][0] > window:
            samples.pop(0)
        rate = 0.0
        if len(samples) >= 2:
            dt = samples[-1][0] - samples[0][0]
            if dt > 0:
                rate = (samples[-1][1] - samples[0][1]) / dt
        eta = f"~{(total - i) / rate / 60:.0f}m left" if rate > 0 else "estimating"
        typer.echo(f"  {label} {i}/{total} ({rate:.0f}/s, {eta})", err=True)

    return report


def _run_ingest(cfg: Config, path: Path, device_folder: str, source_key: str,
                apply: bool, show: int, verify_archive: bool = False):
    """Shared ingest driver for `ingest`, `ingest-drops` and `pull`.

    Always returns an IngestOutcome. `ran` False distinguishes "ingest never
    executed" (no directory, or no files) from "executed and copied nothing" —
    a distinction the coverage decision depends on, and one the old bare-None
    return could not express (005 FR-003).
    """
    from datetime import datetime
    from .catalog import Catalog
    from . import ingest as ing
    from .coverage import IngestOutcome
    from .metadata import extract_batch

    if not path.is_dir():
        typer.secho(f"  {source_key}: {path} is not a directory — skipping.", fg=typer.colors.YELLOW)
        return IngestOutcome(ran=False, reason="not-a-directory")
    files = list(ing._iter_files(path.resolve()))
    if not files:
        typer.secho(f"  {source_key}: no files under {path}.", fg=typer.colors.YELLOW)
        return IngestOutcome(ran=False, reason="no-files")

    cat = Catalog(cfg.catalog_db)
    archive_root = cfg.archive_root.resolve()
    if verify_archive:
        typer.secho("  --verify-archive: re-reading every archived candidate "
                    "(slow, network-bound)", fg=typer.colors.YELLOW)
    # The planning pass is the long one on a big mirror (hashing + catalog
    # lookups), and it used to print nothing at all — a 33k-file sweep looked
    # indistinguishable from a hang for hours.
    _plan_prog = _progress_reporter("planning")

    p = ing.plan(files, device_folder, cat, archive_root, cfg.default_timezone,
                 verify_archive=verify_archive, progress=_plan_prog)

    if p.integrity_warnings:
        typer.secho(
            f"\n  ⚠ ARCHIVE INTEGRITY: {len(p.integrity_warnings)} archived "
            f"file(s) no longer match the hash the catalog recorded for them.",
            fg=typer.colors.RED, bold=True)
        for arc, recorded, actual in p.integrity_warnings[:show]:
            typer.secho(f"    {arc}\n      recorded {recorded[:16]}…  "
                        f"now {actual[:16]}…", fg=typer.colors.RED)
        typer.secho("    These were NOT treated as duplicates — the staged copy "
                    "is kept and filed. Run `archivist scan-archive` to assess "
                    "the archive, and do NOT prune staging until you have.",
                    fg=typer.colors.RED, bold=True)

    typer.secho(f"\n{source_key} -> \"{device_folder}\"  ({len(files)} files)", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  to copy: {len(p.to_copy)} ({_gb(p.copy_bytes)})   already-archived (skip): {len(p.skipped)}")
    for f in p.to_copy[:show]:
        rel = str(Path(f.dst).relative_to(archive_root))
        typer.echo(f"    {Path(f.src).name}  [{f.confidence:<6} {f.date_source}]  ->  {rel}")
    if len(p.to_copy) > show:
        typer.echo(f"    ... and {len(p.to_copy) - show} more")
    for f in p.skipped[:3]:
        typer.secho(f"    skip {Path(f.src).name} (already in archive)", fg=typer.colors.YELLOW)

    if not apply:
        return IngestOutcome(ran=False, reason="dry-run",
                             integrity_warnings=len(p.integrity_warnings))

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    metas = extract_batch([Path(f.src) for f in p.to_copy]) if p.to_copy else {}

    # Same wall-clock cadence as planning. A fixed every-25-items trigger
    # spams thousands of lines when the run is mostly duplicate skips and goes
    # quiet for minutes when it is copying large videos — busiest exactly when
    # there is least to say.
    _apply_prog = _progress_reporter("filing")

    def _prog(i: int, pf) -> None:
        _apply_prog(i, len(p.files))

    res = ing.apply(p, device_folder, cat, archive_root, cfg.default_timezone,
                    run_id, cfg.logs_dir, metas=metas, progress=_prog)
    typer.secho(f"  copied {res.copied} ({_gb(res.copied_bytes)}), skipped {res.skipped}, "
                f"failed {len(res.failed)}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  location: located {res.located}, absent {res.location_absent}, "
               f"rejected {res.location_rejected}"
               + (f", retained-on-duplicate {res.location_retained}" if res.location_retained else ""))
    for src, why in res.failed[:show]:
        typer.secho(f"    FAIL {Path(src).name}: {why}", fg=typer.colors.RED)
    if res.copied:
        typer.echo(f"  manifest: {res.manifest_path}")
    return IngestOutcome(ran=True, copied=res.copied, skipped=res.skipped,
                         failed=len(res.failed), copied_bytes=res.copied_bytes,
                         integrity_warnings=len(p.integrity_warnings))


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="Directory of media to sort."),
    source: str = typer.Option(..., "--source", "-s", help="Source key from config."),
    apply: bool = typer.Option(False, "--apply", help="Actually copy to the archive (default: dry-run)."),
    verify_archive: bool = typer.Option(False, "--verify-archive", help="Re-read every archived candidate to confirm a duplicate (slow)."),
    show: int = typer.Option(12, "--show", help="Sample rows to print."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Sort a directory of media into the archive by date (dry-run by default)."""
    cfg = _load(config)
    if source not in cfg.sources:
        typer.secho(f"Unknown source '{source}'. Known: {', '.join(cfg.sources)}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if apply:
        _require(cfg)
    _run_ingest(cfg, path, cfg.sources[source].device_folder, source, apply, show,
                verify_archive=verify_archive)


@app.command("ingest-drops")
def ingest_drops(
    apply: bool = typer.Option(False, "--apply", help="Actually copy to the archive (default: dry-run)."),
    verify_archive: bool = typer.Option(False, "--verify-archive", help="Re-read every archived candidate to confirm a duplicate (slow)."),
    show: int = typer.Option(8, "--show", help="Sample rows per source."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Process files dropped under work_root/<work_subdir>/drops/<source>/."""
    cfg = _load(config)
    if apply:
        _require(cfg)
    drop_sources = {k: s for k, s in cfg.sources.items() if s.type == "drop"}
    if not drop_sources:
        typer.secho("No 'drop' sources configured.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    typer.secho(f"Ingesting drops from {cfg.drops_dir}", bold=True)
    for key, src in drop_sources.items():
        _run_ingest(cfg, cfg.drops_dir / key, src.device_folder, key, apply, show,
                    verify_archive=verify_archive)


@app.command()
def cleanup(
    dupes: bool = typer.Option(True, "--dupes/--no-dupes", help="Include duplicate copies."),
    corrupt: bool = typer.Option(True, "--corrupt/--no-corrupt", help="Include corrupt (non-media) files."),
    junk: bool = typer.Option(True, "--junk/--no-junk", help="Include .argb preview junk."),
    apply: bool = typer.Option(False, "--apply", help="Move files to _Quarantine (default: dry-run plan only)."),
    show: int = typer.Option(15, "--show", help="Sample rows to print per category."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Quarantine duplicates / corrupt / junk files (archive-only, reversible).

    Dry-run by default. With --apply, files MOVE to <archive_root>/_Quarantine/
    (atomic, reversible) and duplicates are full-hash confirmed first. Nothing is
    ever deleted; a manifest records every move.
    """
    from datetime import datetime
    from .catalog import Catalog
    from . import dedupe as dd

    cfg = _load(config)
    if apply:
        _require(cfg)

    cat = Catalog(cfg.catalog_db)
    if not cat.exists():
        typer.secho("No catalog yet — run `archivist scan-archive` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    p = dd.plan(cat, cfg.archive_root.resolve(), do_dupes=dupes, do_corrupt=corrupt, do_junk=junk)

    def _gb(n: int) -> str:
        return f"{n / 1073741824:.1f} GB"

    typer.secho("Cleanup plan (quarantine):", bold=True)
    for cat_name in ("duplicate", "corrupt", "junk"):
        items = p.by_category(cat_name)
        if not items:
            continue
        cbytes = sum(i.size for i in items)
        typer.secho(f"\n  {cat_name}: {len(items)} files, {_gb(cbytes)}", fg=typer.colors.CYAN, bold=True)
        for it in items[:show]:
            rel = Path(it.archive_path).name
            extra = f"   (keep: {Path(it.keep_path).parent.name}/)" if it.keep_path else ""
            typer.echo(f"    move {rel}{extra}")
        if len(items) > show:
            typer.echo(f"    ... and {len(items) - show} more")

    typer.echo("")
    typer.secho(f"TOTAL: {len(p.items)} files, {_gb(p.total_bytes)} to quarantine.", bold=True)

    if not apply:
        typer.secho(
            "\nDry-run only. Re-run with --apply to move these to _Quarantine "
            "(duplicates are byte-confirmed before moving; nothing is deleted).",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    typer.echo(f"\nApplying (run {run_id}) — moving to {cfg.archive_root}/_Quarantine/{run_id}/ ...")

    def _prog(i: int, item) -> None:
        if i % 20 == 0:
            typer.echo(f"  ...{i}/{len(p.items)}", err=True)

    res = dd.apply(p, cat, cfg.archive_root.resolve(), run_id, cfg.logs_dir, progress=_prog)
    typer.secho(f"\nMoved {len(res.moved)} files ({_gb(res.moved_bytes)}) to quarantine.", fg=typer.colors.GREEN, bold=True)
    if res.skipped:
        typer.secho(f"Skipped {len(res.skipped)} (see below):", fg=typer.colors.YELLOW)
        for it, why in res.skipped[:show]:
            typer.secho(f"  {Path(it.archive_path).name}: {why}", fg=typer.colors.YELLOW)
    typer.echo(f"Manifest: {res.manifest_path}")
    typer.echo("Verify the quarantine, then purge it to reclaim space (purge command TBD).")


@app.command()
def purge(
    run_id: Optional[str] = typer.Argument(None, help="Quarantine run to purge (default: latest manifest)."),
    apply: bool = typer.Option(False, "--apply", help="Permanently delete (IRREVERSIBLE). Default: dry-run."),
    show: int = typer.Option(10, "--show", help="Sample rows to print."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Permanently delete a quarantine run to reclaim space (IRREVERSIBLE).

    Refuses to delete a quarantined duplicate whose kept copy is missing from the
    live archive, and only ever deletes inside <archive_root>/_Quarantine.
    """
    from .catalog import Catalog  # noqa: F401  (kept parallel with other cmds)
    from . import dedupe as dd

    cfg = _load(config)
    if apply:
        _require(cfg)

    # Resolve the manifest for the requested (or latest) run.
    logs = sorted(cfg.logs_dir.glob("cleanup-*.jsonl"))
    if not logs:
        typer.secho("No cleanup manifests found — nothing to purge.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if run_id:
        match = [m for m in logs if run_id in m.name]
        if not match:
            typer.secho(f"No manifest for run '{run_id}'.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        manifest = match[-1]
    else:
        manifest = logs[-1]
    rid = manifest.stem.replace("cleanup-", "")
    run_dir = (cfg.archive_root / dd.QUARANTINE_DIRNAME / rid).resolve()

    entries = dd.load_manifest(manifest)
    plan = dd.purge_plan(entries, cfg.archive_root.resolve())

    def _gb(n: int) -> str:
        return f"{n / 1073741824:.1f} GB"

    typer.secho(f"Purge plan for run {rid}", bold=True)
    typer.echo(f"  manifest:  {manifest}")
    typer.echo(f"  quarantine dir: {run_dir}")
    typer.secho(f"  deletable: {len(plan.deletable)} files, {_gb(plan.free_bytes)}", fg=typer.colors.CYAN)
    for e in plan.deletable[:show]:
        typer.echo(f"    delete {Path(e['to']).name}")
    if plan.protected:
        typer.secho(f"  PROTECTED (kept): {len(plan.protected)} files", fg=typer.colors.YELLOW)
        for e, why in plan.protected[:show]:
            typer.secho(f"    keep {Path(e.get('to','?')).name}: {why}", fg=typer.colors.YELLOW)

    if not apply:
        typer.secho(
            f"\nDry-run. Re-run `archivist purge {rid} --apply` to permanently delete "
            f"{_gb(plan.free_bytes)} (IRREVERSIBLE).",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0)

    typer.secho(f"\nDeleting {len(plan.deletable)} files ({_gb(plan.free_bytes)})... IRREVERSIBLE.", fg=typer.colors.RED, bold=True)

    def _prog(i: int, e) -> None:
        if i % 25 == 0:
            typer.echo(f"  ...{i}/{len(plan.deletable)}", err=True)

    res = dd.purge_apply(plan, cfg.archive_root.resolve(), run_dir, progress=_prog)
    typer.secho(f"\nDeleted {res.deleted} files, freed {_gb(res.freed_bytes)}.", fg=typer.colors.GREEN, bold=True)
    if plan.protected:
        typer.secho(f"Kept {len(plan.protected)} protected files in quarantine.", fg=typer.colors.YELLOW)
    if res.errors:
        typer.secho(f"{len(res.errors)} errors:", fg=typer.colors.RED)
        for path, err in res.errors[:show]:
            typer.secho(f"  {path}: {err}", fg=typer.colors.RED)


@app.command("prune-staging")
def prune_staging(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to one source's staging/drop areas."),
    apply: bool = typer.Option(False, "--apply", help="Actually delete verified-archived staged files (default: plan only)."),
    show: int = typer.Option(10, "--show", help="Sample rows to print per status."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Reclaim working storage: delete staged files whose VERIFIED archived copy exists.

    Deletes ONLY inside the tool's own staging/drops areas, only items whose
    byte-identical archived copy is confirmed present right now. Unverified
    files, files whose archived copy is missing, and anything outside the
    staging roots are refused and reported. Dry-run by default; journaled.
    """
    from datetime import datetime
    from . import staging as st

    cfg = _load(config)
    _require(cfg)  # verification needs the live archive mounted

    cat = Catalog(cfg.catalog_db)
    if not cat.exists():
        typer.secho("No catalog yet — nothing can be verified as archived.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    def _prog(i: int, f) -> None:
        if i % 200 == 0:
            typer.echo(f"  ...{i} staged files examined", err=True)

    p = st.plan(cfg, cat, source=source, progress=_prog)

    typer.secho("Prune plan (staging/drops):", bold=True)
    for status, color in ((st.VERIFIED, typer.colors.CYAN),
                          (st.UNVERIFIED, typer.colors.YELLOW),
                          (st.ARCHIVED_MISSING, typer.colors.RED),
                          (st.ARCHIVE_MISMATCH, typer.colors.RED),
                          (st.OUTSIDE, typer.colors.RED)):
        items = p.by_status(status)
        if not items:
            continue
        typer.secho(f"\n  {status}: {len(items)} files, {_gb(sum(i.size for i in items))}",
                    fg=color, bold=True)
        for it in items[:show]:
            typer.echo(f"    {Path(it.path).name}")
        if len(items) > show:
            typer.echo(f"    ... and {len(items) - show} more")
    if p.by_status(st.ARCHIVED_MISSING):
        typer.secho(
            "\n⚠ archived-missing: these staged files have a catalog entry whose "
            "archived copy is ABSENT — investigate archive integrity before "
            "anything else. They will never be pruned.",
            fg=typer.colors.RED, bold=True,
        )

    typer.echo("")
    typer.secho(f"Prunable now: {len(p.by_status(st.VERIFIED))} files, "
                f"{_gb(p.prunable_bytes)}.", bold=True)
    typer.echo("  (provisional: each archived counterpart is re-read and "
               "byte-compared immediately before its staged copy is deleted)")

    if not apply:
        typer.secho("\nDry-run only. Re-run with --apply to delete the "
                    "verified-archived files above (journaled).", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    def _dprog(i: int, it) -> None:
        if i % 100 == 0:
            typer.echo(f"  ...{i} deleted", err=True)

    res = st.apply(p, cfg, run_id, progress=_dprog)
    typer.secho(f"\nDeleted {res.deleted} staged files, reclaimed {_gb(res.freed_bytes)}.",
                fg=typer.colors.GREEN, bold=True)
    if res.refused:
        typer.echo("  refused: " + ", ".join(f"{k}={v}" for k, v in sorted(res.refused.items())))
    if res.refused.get(st.ARCHIVE_MISMATCH):
        typer.secho(
            f"\n⚠ {res.refused[st.ARCHIVE_MISMATCH]} staged file(s) were KEPT because their "
            f"archived counterpart's bytes no longer match. The staged copies "
            f"may now be the only good ones — run `archivist scan-archive` and "
            f"assess the archive before pruning again.",
            fg=typer.colors.RED, bold=True)
    for path, err in res.errors[:show]:
        typer.secho(f"  ERROR {Path(path).name}: {err}", fg=typer.colors.RED)
    typer.echo(f"  manifest: {res.manifest_path}")


auth_app = typer.Typer(no_args_is_help=True, help="Authenticate cloud sources (one-time / on session expiry).")
pull_app = typer.Typer(no_args_is_help=True, help="Pull media from cloud sources into the archive.")
app.add_typer(auth_app, name="auth")
app.add_typer(pull_app, name="pull")


def _icloud_source(cfg: Config, source: str):
    if source not in cfg.sources:
        typer.secho(f"Unknown source '{source}'. Known: {', '.join(cfg.sources)}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    src = cfg.sources[source]
    if src.type != "icloud":
        typer.secho(f"Source '{source}' is type '{src.type}', not icloud.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if not src.username:
        typer.secho(f"Source '{source}' has no `username` (Apple ID) in config.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    return src


@auth_app.command("icloud")
def auth_icloud(
    source: str = typer.Option(..., "--source", "-s", help="iCloud source key from config."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """One-time interactive iCloud login (password + 2FA). Stores session + Keychain password."""
    from . import icloud
    from .doctor import probe_keyring

    cfg = _load(config)
    src = _icloud_source(cfg, source)
    kr_ok, kr_detail = probe_keyring()
    if not kr_ok:
        typer.secho(
            "Refusing to authenticate — no functional SECURE keyring backend on "
            f"this host ({kr_detail}).\nCredentials are never stored in plaintext. "
            "Provision the platform keyring first (macOS: Keychain is built in; "
            "Linux: gnome-keyring via Secret Service — see docs/linux-host.md §2), "
            "then re-run.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)
    typer.echo(f"Authenticating iCloud for {src.username} (enter password + 2FA when prompted)...")
    try:
        rc = icloud.auth(src.username, cfg.icloud_session_dir)
    except icloud.ICloudError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if rc == 0:
        typer.secho("iCloud session established. Pulls can now run non-interactively.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"icloudpd auth exited {rc}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=rc)


@dataclass
class PullOutcome:
    """Per-source result, so `pull all` can report without re-deriving it.

    `status` carries the distinction whose absence let the 2026-09-26 coverage
    loss pass unnoticed: IDLE means "proven nothing to do", FAILED means "could
    not do its work". Both used to print as `OK ... copied 0`.
    """
    source: str
    status: str                    # ok | idle | partial | failed | bootstrap
                                   #    | config-invalid
    detail: str = ""
    copied: int = 0
    copied_bytes: int = 0
    skipped: int = 0
    failed: int = 0
    mode: str = ""
    examined: int = 0
    downloaded: int = 0
    elapsed_s: float = 0.0
    advanced_to: str | None = None
    reconciled: bool = False
    reconcile_due_days: int | None = None   # None when never reconciled
    reconcile_stale: bool = False           # the fact the summary reports on
    integrity_warnings: int = 0

    @property
    def ok(self) -> bool:
        """True when nothing about this source needs the operator's attention."""
        return self.status in ("ok", "idle", "partial")


_STATUS_STYLE = {
    "ok":             ("OK      ", typer.colors.GREEN),
    "idle":           ("IDLE    ", typer.colors.BRIGHT_BLACK),
    "partial":        ("PARTIAL ", typer.colors.YELLOW),
    "failed":         ("FAILED  ", typer.colors.RED),
    "bootstrap":      ("BOOTSTRP", typer.colors.MAGENTA),
    "config-invalid": ("CONFIG  ", typer.colors.RED),
}


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _pull_one(cfg: Config, source: str, *, recent=None, since=None, until=None,
              until_found=None, full=False, no_download=False, apply=False,
              show=12, verbose=False, no_reconcile=False,
              verify_archive=False, run_id: str | None = None) -> PullOutcome:
    """Pull + ingest ONE iCloud source. Returns an outcome instead of exiting,
    so a multi-source run can carry on past a failure.

    The watermark discipline lives in `coverage.decide_advance`: this function
    gathers evidence (mode, proof, ingest outcome), journals what the decision
    claimed, and only then touches the catalog.
    """
    from datetime import datetime as _dt
    from . import icloud
    from .coverage import (UNBOUNDED_MODES, Advance, IngestOutcome, PullMode,
                           append_record, build_record, decide_advance,
                           may_advance_reconcile, resolve_mode)

    src = _icloud_source(cfg, source)
    cat = Catalog(cfg.catalog_db)
    state_key = icloud.pull_state_key(source)
    rec_key = icloud.reconcile_state_key(source)
    run_id = run_id or _dt.now().strftime("%Y%m%d-%H%M%S")
    run_started = _dt.now().replace(microsecond=0)

    explicit_window = (recent is not None or since is not None or until is not None
                       or until_found is not None or full)

    last_pull = last_reconcile = None
    if cat.exists():
        with cat.connect() as conn:
            last_pull = cat.get_meta(conn, state_key)
            last_reconcile = cat.get_meta(conn, rec_key)

    prev_watermark = None
    watermark_unreadable = None
    if last_pull:
        try:
            prev_watermark = _dt.fromisoformat(last_pull)
        except ValueError:
            # Present but unparseable: distinct from absent, and refused
            # rather than quietly downgraded to "no watermark" (which would
            # disable the --since span guard).
            watermark_unreadable = last_pull

    interval = cfg.reconcile_interval_for(source)
    # Staleness is computed regardless, so the summary can report an overdue
    # source even when escalation is switched off. Suppressing the sweep must
    # never suppress the warning.
    is_stale = icloud.is_reconcile_due(last_reconcile, run_started, interval)
    escalation_allowed = cfg.auto_reconcile and not no_reconcile
    reconcile_due = (escalation_allowed and not explicit_window
                     and not no_download and is_stale)
    due_days = None
    if last_reconcile:
        try:
            due_days = (run_started - _dt.fromisoformat(last_reconcile)).days
        except ValueError:
            due_days = None

    if full and since:
        typer.secho(
            "--full and --since are contradictory: --full sweeps the entire "
            "library, so the date would be ignored. Drop one.",
            fg=typer.colors.RED, err=True)
        return PullOutcome(source, "config-invalid",
                           "--full and --since cannot be combined")

    if not explicit_window and not no_download:
        if last_pull is None:
            typer.secho(
                f"No pull state for '{source}' on this host — refusing a stateless "
                "full-library pull.\nUse an explicit window: --recent N, "
                "--since YYYY-MM-DD, or --full for a deliberate bootstrap.",
                fg=typer.colors.RED, err=True,
            )
            return PullOutcome(source, "bootstrap",
                               "needs an explicit --full/--since bootstrap")
        since = icloud.window_since(last_pull)

    mode = resolve_mode(no_download=no_download, recent=recent,
                        until_found=until_found, until=until, full=full,
                        since=since if explicit_window else None,
                        reconcile_due=reconcile_due)

    # A routine refresh bounds its enumeration; a sweep deliberately does not.
    scan_bound = None
    if mode is PullMode.ROUTINE_BOUNDED:
        scan_bound = cfg.scan_bound_for(source)
        recent = scan_bound
    elif mode in UNBOUNDED_MODES:
        # A sweep drops BOTH bounds, including the date filter (data-model §4:
        # "Downloader bounds: none"). Keeping the date filter would make the
        # sweep unable to see the very thing it exists for — media added
        # recently but CAPTURED long ago, which by definition predates the
        # watermark. An unbounded sweep re-downloads what the mirror no longer
        # holds; catalog dedup means nothing is re-filed, but the working
        # volume must have room for it (see README, staged sweeps).
        since = None

    if mode is PullMode.RECONCILE:
        ago = f"{due_days}d ago" if due_days is not None else "never"
        typer.secho(
            f"  reconciliation due (last swept {last_reconcile or 'never'}, {ago})"
            " — this will take longer", fg=typer.colors.MAGENTA, bold=True)
        typer.echo(f"  full sweep, items created since {since}"
                   if since else "  full sweep, entire library")
    elif mode is PullMode.ROUTINE_BOUNDED:
        typer.echo(f"  routine: bounded scan ({scan_bound}), "
                   f"items created since {since}")
    elif full:
        typer.secho("  (--full: entire library — bootstrap-scale download)",
                    fg=typer.colors.YELLOW)

    mirror = cfg.icloud_dir / source
    proof = icloud.CoverageProof()
    if not no_download:
        typer.echo(f"  downloading ({src.username}) -> {mirror}")
        try:
            proof = icloud.download(src.username, mirror, cfg.icloud_session_dir,
                                    recent=recent, until_found=until_found,
                                    since=since, until=until, verbose=verbose)
        except icloud.ICloudError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            return PullOutcome(source, "failed", str(exc), mode=mode.value)
        typer.echo(f"  examined {proof.examined}, downloaded {proof.downloaded}, "
                   f"already present {proof.already_present}"
                   f"        [{_fmt_elapsed((_dt.now() - run_started).total_seconds())}]")
        if not proof.parser_confident:
            needs_auth = any("two-factor" in n for n in proof.notes)
            if needs_auth:
                # Distinct from a generic failure: there is one obvious next
                # step and it needs a human at the keyboard.
                typer.secho(
                    f"\n  iCloud needs you to sign in again for '{source}'.\n"
                    f"  This command cannot prompt for the code (it reads "
                    f"icloudpd's output to verify coverage), so it stopped "
                    f"rather than wait silently.\n\n"
                    f"      archivist auth icloud --source {source}\n\n"
                    f"  Then re-run this command. Nothing was changed.",
                    fg=typer.colors.YELLOW, bold=True, err=True,
                )
            else:
                typer.secho(
                    f"  icloudpd run could not be confirmed: {proof.note_text()}\n"
                    f"  If the session expired, run `archivist auth icloud "
                    f"--source {source}` and retry.",
                    fg=typer.colors.RED, err=True,
                )

    # Hand the mirror to the Phase 2 ingest engine.
    ing_out = _run_ingest(cfg, mirror, src.device_folder, source, apply, show,
                          verify_archive=verify_archive)

    decision = decide_advance(
        mode, proof, ing_out, applying=apply, run_started=run_started,
        previous_watermark=prev_watermark,
        window_since=(_dt.fromisoformat(since).date() if since else None),
        scan_bound=scan_bound, watermark_unreadable=watermark_unreadable,
    )
    run_finished = _dt.now().replace(microsecond=0)

    out = PullOutcome(source, "ok", mode=mode.value, examined=proof.examined,
                      downloaded=proof.downloaded,
                      elapsed_s=(run_finished - run_started).total_seconds(),
                      reconcile_due_days=due_days, reconcile_stale=is_stale)
    out.copied, out.copied_bytes = ing_out.copied, ing_out.copied_bytes
    out.skipped, out.failed = ing_out.skipped, ing_out.failed
    out.integrity_warnings = ing_out.integrity_warnings

    if apply:
        # Journal FIRST, then the catalog (constitution Principle IV): an
        # interruption between the two leaves a stale watermark, never a
        # premature one.
        record = build_record(
            source=source, run_id=run_id, mode=mode, run_started=run_started,
            run_finished=run_finished, window_since=since, window_until=until,
            scan_bound=scan_bound, proof=proof, ingest=ing_out, decision=decision)
        append_record(cfg.pull_journal_path(run_id), record)

    if isinstance(decision, Advance) and apply:
        with cat.connect() as conn:
            claimed = decision.claimed_through.isoformat()
            cat.set_meta(conn, state_key, claimed)
            cat.set_meta(conn, icloud.coverage_key(source), record.to_json())
            if may_advance_reconcile(mode, decision, ing_out):
                cat.set_meta(conn, rec_key, claimed)
                out.reconciled = True
            conn.commit()
        out.advanced_to = claimed
        typer.secho(f"  coverage advanced -> {claimed}", fg=typer.colors.GREEN)
        if out.reconciled:
            typer.secho(f"  reconciled through {claimed}", fg=typer.colors.GREEN)
        if ing_out.copied == 0 and proof.downloaded == 0:
            out.status = "idle"
    elif apply:
        out.status = "failed" if _is_failure(decision.reason) else "partial"
        out.detail = decision.reason or ""
        typer.secho(f"  coverage NOT advanced: {decision.reason}",
                    fg=typer.colors.YELLOW if out.status == "partial" else typer.colors.RED)
    else:
        out.status = "idle" if ing_out.copied == 0 else "ok"
        out.detail = decision.reason or ""

    return out


#: Refusals that mean the run could not do its work, as opposed to refusals
#: that mean it did real work but declined to over-claim.
_FAILURE_MARKERS = ("could not be confirmed", "enumeration did not complete",
                    "failed to copy", "never reached ingest")


def _is_failure(reason: str | None) -> bool:
    return bool(reason) and any(m in reason for m in _FAILURE_MARKERS)


@pull_app.command("icloud")
def pull_icloud(
    source: str = typer.Option(..., "--source", "-s", help="iCloud source key from config."),
    recent: Optional[int] = typer.Option(None, "--recent", help="Only the N most recent items (never advances coverage)."),
    since: Optional[str] = typer.Option(None, "--since", help="Skip items created before this date (YYYY-MM-DD)."),
    until: Optional[str] = typer.Option(None, "--until", help="Skip items created after this date (YYYY-MM-DD) — pairs with --since for range slices."),
    until_found: Optional[int] = typer.Option(None, "--until-found", help="Stop after N already-downloaded (never advances coverage)."),
    full: bool = typer.Option(False, "--full", help="Bootstrap: pull the ENTIRE library (large/long)."),
    no_download: bool = typer.Option(False, "--no-download", help="Skip icloudpd; just ingest the existing mirror."),
    apply: bool = typer.Option(False, "--apply", help="Write to the archive (default: download + dry-run ingest)."),
    verbose: bool = typer.Option(False, "--verbose", help="Show icloudpd's raw per-item output."),
    no_reconcile: bool = typer.Option(False, "--no-reconcile", help="Never escalate to a full sweep, even if this source is due."),
    verify_archive: bool = typer.Option(False, "--verify-archive", help="Re-read every archived candidate to confirm a duplicate (slow; default trusts the catalog's recorded hash plus a 1% sample)."),
    show: int = typer.Option(12, "--show", help="Sample rows to print."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Pull an iCloud library window to the work drive, then ingest into the archive.

    Routine (no window flags): pulls items created since the last successful
    pull minus a 7-day overlap, bounded to the most recently added `scan_bound`
    items, and escalates to a full sweep when reconciliation is due.

    `--since D` is the repair tool for a known gap: with no upper bound and no
    count bound it may advance coverage, but only when D is at or before the
    current watermark — a later D would silently skip the span between.
    """
    from datetime import date as _date

    cfg = _load(config)
    _icloud_source(cfg, source)   # validate before touching the mounts
    for flag, value in (("--since", since), ("--until", until)):
        if value is None:
            continue
        try:
            _date.fromisoformat(value)
        except ValueError:
            typer.secho(f"{flag} must be a YYYY-MM-DD date, got {value!r}",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    _require(cfg)  # need both mounts: work drive (mirror) + archive (ingest)
    typer.secho(f"\n=== {source} ===", fg=typer.colors.CYAN, bold=True)
    out = _pull_one(cfg, source, recent=recent, since=since, until=until,
                    until_found=until_found, full=full, no_download=no_download,
                    apply=apply, show=show, verbose=verbose,
                    no_reconcile=no_reconcile, verify_archive=verify_archive)
    if not out.ok:
        raise typer.Exit(code=1 if out.status != "config-invalid" else 2)


@pull_app.command("all")
def pull_all(
    apply: bool = typer.Option(False, "--apply", help="Write to the archive (default: download + dry-run ingest)."),
    show: int = typer.Option(6, "--show", help="Sample rows to print per source."),
    verbose: bool = typer.Option(False, "--verbose", help="Show icloudpd's raw per-item output."),
    no_reconcile: bool = typer.Option(False, "--no-reconcile", help="Never escalate to a full sweep this run (still reports what is overdue)."),
    verify_archive: bool = typer.Option(False, "--verify-archive", help="Re-read every archived candidate to confirm a duplicate (slow; default trusts the catalog's recorded hash plus a 1% sample)."),
    stop_on_error: bool = typer.Option(False, "--stop-on-error", help="Abort at the first failing source (default: continue)."),
    config: Optional[str] = ConfigOpt,
) -> None:
    """Routine refresh: windowed pull + ingest for EVERY iCloud source.

    Each source takes a bounded scan since its own coverage watermark, or an
    unbounded reconciliation sweep when it has gone too long without one. A
    source that fails does not advance its watermark and does not stop the
    others; the summary says what to re-run.
    """
    from datetime import datetime as _dt

    cfg = _load(config)
    icloud_sources = [k for k, s in cfg.sources.items() if s.type == "icloud"]
    if not icloud_sources:
        typer.secho("No 'icloud' sources configured.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    _require(cfg)

    # Name the config: discovery falls back to ~/.config/archivist/config.yaml
    # when cwd has none, and a stale one there silently changes WHICH accounts
    # (and which device folders) a run touches. Never leave that implicit.
    typer.echo(f"config: {cfg.path}")
    for warning in small_scan_bound_warnings(cfg):
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)
    typer.secho(f"Refreshing {len(icloud_sources)} iCloud source(s): "
                f"{', '.join(icloud_sources)}", bold=True)
    if not apply:
        typer.secho("Dry-run: downloads still happen, archive writes do NOT "
                    "(re-run with --apply).", fg=typer.colors.YELLOW)

    run_id = _dt.now().strftime("%Y%m%d-%H%M%S")
    outcomes: list[PullOutcome] = []
    for i, key in enumerate(icloud_sources, 1):
        typer.secho(f"\n=== [{i}/{len(icloud_sources)}] {key} ===",
                    fg=typer.colors.CYAN, bold=True)
        try:
            out = _pull_one(cfg, key, apply=apply, show=show, verbose=verbose,
                            no_reconcile=no_reconcile, run_id=run_id,
                            verify_archive=verify_archive)
        except typer.Exit:                      # config-level rejection
            out = PullOutcome(key, "config-invalid",
                              "see the error above — fix config.yaml, not the account")
        except Exception as exc:                # never let one source sink the run
            typer.secho(f"  unexpected error: {exc}", fg=typer.colors.RED, err=True)
            out = PullOutcome(key, "failed", str(exc))
        outcomes.append(out)
        if not out.ok and stop_on_error:
            typer.secho("Stopping (--stop-on-error).", fg=typer.colors.RED, err=True)
            break

    typer.secho("\nRefresh summary", bold=True)
    for o in outcomes:
        label, color = _STATUS_STYLE.get(o.status, ("?       ", typer.colors.WHITE))
        line = f"  {label} {o.source:<16} "
        if o.status in ("ok", "idle"):
            cover = f"covered through {o.advanced_to[:10]}" if o.advanced_to else "coverage unchanged"
            if o.reconciled:
                cover = f"covered + reconciled {o.advanced_to[:10]}"
            line += (f"copied {o.copied} ({_gb(o.copied_bytes)}), {cover}"
                     if o.copied else f"nothing new, {cover}")
        elif o.status == "partial":
            line += f"copied {o.copied} ({_gb(o.copied_bytes)}), coverage held"
        else:
            line += o.detail or o.status
        typer.secho(line, fg=color)
        if o.status == "partial" and o.detail:
            typer.secho(f"           {o.detail}", fg=color)

    overdue = [o for o in outcomes if o.reconcile_stale and not o.reconciled]
    if overdue:
        def _age(o: PullOutcome) -> str:
            return f"{o.reconcile_due_days}d" if o.reconcile_due_days is not None else "never"
        typer.secho("\n  reconciliation due: "
                    + ", ".join(f"{o.source} ({_age(o)})" for o in overdue),
                    fg=typer.colors.YELLOW)
        typer.echo("    sweep one at a time, pruning between:")
        typer.echo(f"      archivist pull icloud --source {overdue[0].source} --full --apply")
        typer.echo("      archivist prune-staging --apply")

    bad = [o for o in outcomes if not o.ok]
    missing = [o.source for o in outcomes if o.status == "bootstrap"]
    if missing:
        typer.echo("\nBootstrap the never-pulled source(s) first, e.g.:")
        for m in missing:
            typer.echo(f"  archivist pull icloud --source {m} --full --apply")
    rotted = sum(o.integrity_warnings for o in outcomes)
    if rotted:
        typer.secho(
            f"\n  ⚠ {rotted} archived file(s) disagreed with the catalog. Do NOT "
            f"prune staging yet — run `archivist scan-archive` and assess the "
            f"archive first. The staged copies are the safe ones right now.",
            fg=typer.colors.RED, bold=True)
    elif apply and not bad:
        typer.echo("\n  next: archivist prune-staging (then --apply) to reclaim "
                   "the working mirrors.")
    if bad:
        raise typer.Exit(code=1)



def main() -> None:
    app()


if __name__ == "__main__":
    main()
