"""Load: land raw payloads, merge clean records into the curated table, and
keep the run log that drives incremental loading."""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

CORE_COLUMNS = (
    "event_id", "occurred_at", "source_updated_at", "magnitude", "magnitude_type",
    "place", "region", "latitude", "longitude", "depth_km", "event_type",
    "review_status", "tsunami_flag", "significance", "felt_reports", "detail_url",
)


# --- run log / watermark -----------------------------------------------------

def get_watermark(conn: psycopg.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT max(max_source_updated_at) FROM etl.pipeline_runs WHERE status = 'success'"
    ).fetchone()
    return row[0]


def start_run(conn, source: str, window_start, updated_after) -> int:
    run_id = conn.execute(
        "INSERT INTO etl.pipeline_runs (source, window_start, updated_after)"
        " VALUES (%s, %s, %s) RETURNING run_id",
        (source, window_start, updated_after),
    ).fetchone()[0]
    conn.commit()  # committed immediately so even a crashed run is visible
    return run_id


def finish_run(conn, run_id: int, status: str, stats: dict | None = None,
               max_source_updated_at=None, error: str | None = None) -> None:
    stats = stats or {}
    conn.execute(
        """
        UPDATE etl.pipeline_runs
           SET finished_at = now(), status = %s, fetched = %s, valid = %s,
               duplicates = %s, inserted = %s, updated = %s, unchanged = %s,
               rejected = %s, max_source_updated_at = %s, error_message = %s
         WHERE run_id = %s
        """,
        (status, stats.get("fetched"), stats.get("valid"), stats.get("duplicates"),
         stats.get("inserted"), stats.get("updated"), stats.get("unchanged"),
         stats.get("rejected"), max_source_updated_at, error, run_id),
    )
    conn.commit()


# --- data ----------------------------------------------------------------------

def load_raw(conn, run_id: int, pairs: list[tuple[dict, dict]]) -> None:
    """Append every received version once; re-reads of the same version are ignored."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw.usgs_events (run_id, event_id, source_updated_at, payload)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (event_id, source_updated_at) DO NOTHING",
            [(run_id, rec["event_id"], rec["source_updated_at"], Jsonb(feat)) for feat, rec in pairs],
        )


def merge_core(conn, run_id: int, records: list[dict]) -> tuple[int, int]:
    """Bulk-load into a temp staging table with COPY, then upsert set-based.

    A row is only overwritten when the incoming version is newer, so replays
    and overlapping windows are harmless (idempotent loads).
    Returns (inserted, updated).
    """
    if not records:
        return 0, 0
    cols = ", ".join(CORE_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE stg_earthquakes"
            " (LIKE core.earthquakes INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        cur.execute("ALTER TABLE stg_earthquakes ALTER COLUMN run_id DROP NOT NULL")
        with cur.copy(f"COPY stg_earthquakes ({cols}) FROM STDIN") as copy:
            for rec in records:
                copy.write_row([rec[c] for c in CORE_COLUMNS])

        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in CORE_COLUMNS if c != "event_id")
        cur.execute(
            f"""
            INSERT INTO core.earthquakes ({cols}, run_id)
            SELECT {cols}, %s FROM stg_earthquakes
            ON CONFLICT (event_id) DO UPDATE
               SET {updates}, last_loaded_at = now(), run_id = EXCLUDED.run_id
             WHERE core.earthquakes.source_updated_at < EXCLUDED.source_updated_at
            RETURNING (xmax = 0) AS is_insert
            """,
            (run_id,),
        )
        flags = [row[0] for row in cur.fetchall()]
    inserted = sum(flags)
    return inserted, len(flags) - inserted


def load_rejected(conn, run_id: int, rejected: list[tuple[dict, dict, list[str]]]) -> None:
    if not rejected:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.rejected_events (run_id, event_id, reasons, payload)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT ((coalesce(event_id, '')), (md5(payload::text))) DO NOTHING",
            [(run_id, rec.get("event_id"), reasons, Jsonb(feat)) for feat, rec, reasons in rejected],
        )
