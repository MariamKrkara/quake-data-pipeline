"""End-to-end tests against a real PostgreSQL database.

Set TEST_DATABASE_URL to a throwaway database; the tests drop and recreate
the pipeline schemas. Skipped when the variable is not set.
"""

import os
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from pipeline.config import Settings
from pipeline.db import migrate
from pipeline.runner import run_once

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


@pytest.fixture()
def conn():
    with psycopg.connect(URL) as c:
        c.execute("DROP SCHEMA IF EXISTS raw, core, etl CASCADE")
        c.commit()
        migrate(c)
        yield c


def run(conn, fixture):
    return run_once(conn, Settings(database_url=URL), source_file=str(FIXTURES / fixture), now=NOW)


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_initial_load(conn):
    stats = run(conn, "usgs_batch_1.geojson")
    assert stats["fetched"] == 10
    assert stats["inserted"] == 7 and stats["updated"] == 0
    assert stats["duplicates"] == 1 and stats["rejected"] == 2
    assert scalar(conn, "SELECT count(*) FROM core.earthquakes") == 7
    assert scalar(conn, "SELECT count(*) FROM core.rejected_events") == 2
    assert scalar(conn, "SELECT count(*) FROM raw.usgs_events") == 10


def test_incremental_update_and_insert(conn):
    run(conn, "usgs_batch_1.geojson")
    stats = run(conn, "usgs_batch_2.geojson")
    assert (stats["inserted"], stats["updated"], stats["unchanged"]) == (2, 2, 1)
    assert scalar(conn, "SELECT count(*) FROM core.earthquakes") == 9
    assert scalar(conn, "SELECT magnitude FROM core.earthquakes WHERE event_id = 'us7000r1d4'") == Decimal("5.0")
    # raw keeps both versions of the revised event for audit
    assert scalar(conn, "SELECT count(*) FROM raw.usgs_events WHERE event_id = 'us7000r1d4'") == 2


def test_replay_is_idempotent(conn):
    run(conn, "usgs_batch_1.geojson")
    run(conn, "usgs_batch_2.geojson")
    before = conn.execute("SELECT event_id, magnitude, source_updated_at FROM core.earthquakes ORDER BY 1").fetchall()
    stats = run(conn, "usgs_batch_1.geojson")  # older data arrives again
    after = conn.execute("SELECT event_id, magnitude, source_updated_at FROM core.earthquakes ORDER BY 1").fetchall()
    assert before == after
    assert stats["inserted"] == 0 and stats["updated"] == 0
    assert scalar(conn, "SELECT count(*) FROM core.rejected_events") == 2  # not duplicated


def test_watermark_advances(conn):
    run(conn, "usgs_batch_1.geojson")
    first = scalar(conn, "SELECT max_source_updated_at FROM etl.pipeline_runs WHERE run_id = (SELECT max(run_id) FROM etl.pipeline_runs)")
    run(conn, "usgs_batch_2.geojson")
    second = scalar(conn, "SELECT max_source_updated_at FROM etl.pipeline_runs WHERE run_id = (SELECT max(run_id) FROM etl.pipeline_runs)")
    assert second > first


def test_failed_run_is_recorded_and_rolled_back(conn):
    with pytest.raises(FileNotFoundError):
        run(conn, "does_not_exist.geojson")
    status, error = conn.execute("SELECT status, error_message FROM etl.pipeline_runs").fetchone()
    assert status == "failed" and "FileNotFoundError" in error
    assert scalar(conn, "SELECT count(*) FROM core.earthquakes") == 0


def test_views(conn):
    run(conn, "usgs_batch_1.geojson")
    assert scalar(conn, "SELECT sum(events) FROM core.v_daily_summary") == 7
    assert scalar(conn, "SELECT max_magnitude FROM core.v_region_summary WHERE region = 'Taiwan'") == Decimal("6.1")
