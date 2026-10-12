-- Reporting views on top of the curated table.

CREATE OR REPLACE VIEW core.v_daily_summary AS
SELECT
    (occurred_at AT TIME ZONE 'UTC')::date          AS day_utc,
    count(*)                                         AS events,
    round(avg(magnitude), 2)                         AS avg_magnitude,
    max(magnitude)                                   AS max_magnitude,
    count(*) FILTER (WHERE magnitude >= 5)           AS m5_plus_events
FROM core.earthquakes
GROUP BY 1;

CREATE OR REPLACE VIEW core.v_region_summary AS
SELECT
    region,
    count(*)                                         AS events,
    max(magnitude)                                   AS max_magnitude,
    round(avg(depth_km)::numeric, 1)                 AS avg_depth_km,
    max(occurred_at)                                 AS last_event_at
FROM core.earthquakes
GROUP BY region;

-- Operational view: how each run went.
CREATE OR REPLACE VIEW etl.v_run_health AS
SELECT
    run_id,
    started_at,
    finished_at - started_at                         AS duration,
    status,
    fetched,
    inserted,
    updated,
    unchanged,
    rejected,
    round(100.0 * rejected / nullif(fetched, 0), 2)  AS rejected_pct,
    error_message
FROM etl.pipeline_runs;
