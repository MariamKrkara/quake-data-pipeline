"""Command-line entry point.

    python -m pipeline migrate              apply SQL migrations
    python -m pipeline run                  one incremental run (used by the K8s CronJob)
    python -m pipeline run --loop           run every INTERVAL_MINUTES (used by Docker Compose)
    python -m pipeline run --source-file F  load a saved GeoJSON file instead of the API
    python -m pipeline status               recent runs and table counts
"""

import argparse
import logging
import signal
import sys
import time

import psycopg

from .config import Settings
from .db import connect, migrate
from .runner import run_once

log = logging.getLogger("pipeline")


def _status(conn) -> None:
    print("Recent runs:")
    rows = conn.execute(
        "SELECT run_id, status, started_at::timestamp(0), fetched, inserted, updated,"
        " unchanged, rejected, error_message FROM etl.v_run_health ORDER BY run_id DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        print("  run={} status={} started={} fetched={} inserted={} updated={} unchanged={} rejected={}{}".format(
            *r[:8], f" error={r[8]}" if r[8] else ""))
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM core.earthquakes), (SELECT count(*) FROM raw.usgs_events),"
        " (SELECT count(*) FROM core.rejected_events)"
    ).fetchone()
    print(f"Rows: core.earthquakes={counts[0]} raw.usgs_events={counts[1]} core.rejected_events={counts[2]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    run_p = sub.add_parser("run")
    run_p.add_argument("--loop", action="store_true")
    run_p.add_argument("--source-file")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Exit cleanly when Docker/Kubernetes stops the container.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = Settings.from_env()
    with connect(settings.database_url) as conn:
        migrate(conn)
        if args.command == "migrate":
            return 0
        if args.command == "status":
            _status(conn)
            return 0

        if not args.loop:
            run_once(conn, settings, source_file=args.source_file)
            return 0

        while True:
            try:
                run_once(conn, settings, source_file=args.source_file)
            except psycopg.OperationalError:
                raise  # lost the database: exit so Docker/K8s restarts us with a fresh connection
            except Exception:  # already logged and recorded; keep the service alive
                pass
            log.info("sleeping %s minutes", settings.interval_minutes)
            time.sleep(settings.interval_minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main())
