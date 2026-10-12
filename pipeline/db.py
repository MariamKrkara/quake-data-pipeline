"""Database connection and a minimal, ordered SQL migration runner."""

import logging
import time
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def connect(url: str, attempts: int = 10, delay: float = 3.0) -> psycopg.Connection:
    """Connect, retrying while the database container is still starting."""
    for attempt in range(1, attempts + 1):
        try:
            return psycopg.connect(url)
        except psycopg.OperationalError as exc:
            if attempt == attempts:
                raise
            log.warning("database not ready (attempt %s/%s): %s", attempt, attempts, exc)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def migrate(conn: psycopg.Connection, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply sql/NNN_*.sql files once each, in order. Returns files applied."""
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS etl")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS etl.schema_migrations ("
            " filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    applied = {row[0] for row in conn.execute("SELECT filename FROM etl.schema_migrations")}
    conn.commit()

    newly_applied = []
    for path in sorted(sql_dir.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO etl.schema_migrations (filename) VALUES (%s)", (path.name,))
        log.info("applied migration %s", path.name)
        newly_applied.append(path.name)
    return newly_applied
