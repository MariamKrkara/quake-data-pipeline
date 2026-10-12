"""Orchestrates one pipeline run: watermark -> extract -> transform ->
validate -> load, all data writes in a single transaction."""

import logging
from datetime import datetime, timedelta, timezone

import psycopg

from . import extract, load
from .config import Settings
from .quality import split_valid
from .transform import dedupe_latest, transform_feature

log = logging.getLogger(__name__)


def run_once(conn: psycopg.Connection, settings: Settings,
             source_file: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    watermark = load.get_watermark(conn)

    if watermark is None:  # first run: backfill history
        window_start = now - timedelta(days=settings.backfill_days)
        updated_after = None
    else:                  # incremental: only events changed since last success
        window_start = now - timedelta(days=settings.lookback_days)
        updated_after = watermark - timedelta(minutes=settings.overlap_minutes)

    source = f"file:{source_file}" if source_file else "usgs_api"
    run_id = load.start_run(conn, source, window_start, updated_after)
    log.info("run %s started source=%s window_start=%s updated_after=%s",
             run_id, source, window_start, updated_after)

    try:
        features = (extract.read_file(source_file) if source_file
                    else extract.fetch_events(settings, window_start, updated_after))

        pairs = [(f, transform_feature(f)) for f in features]
        valid, rejected = split_valid(pairs, now)
        valid, duplicates = dedupe_latest(valid)

        with conn.transaction():
            load.load_raw(conn, run_id, pairs)
            inserted, updated = load.merge_core(conn, run_id, valid)
            load.load_rejected(conn, run_id, rejected)

        stats = {
            "fetched": len(features),
            "valid": len(valid),
            "duplicates": duplicates,
            "inserted": inserted,
            "updated": updated,
            "unchanged": len(valid) - inserted - updated,
            "rejected": len(rejected),
        }
        # Advance the watermark only as far as data we actually loaded.
        new_watermark = max([r["source_updated_at"] for r in valid] + ([watermark] if watermark else []),
                            default=None)
        load.finish_run(conn, run_id, "success", stats, new_watermark)
        log.info("run %s succeeded %s", run_id, stats)
        return {"run_id": run_id, **stats}

    except Exception as exc:
        conn.rollback()
        load.finish_run(conn, run_id, "failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        log.exception("run %s failed", run_id)
        raise
