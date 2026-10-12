-- Layered schema:
--   raw  : every API record exactly as received (JSONB), one row per event version
--   core : cleaned, typed, deduplicated table that analysts query
--   etl  : pipeline metadata (run log / watermark)

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS etl;

-- One row per pipeline execution. The highest max_source_updated_at of a
-- successful run is the watermark for the next incremental load.
CREATE TABLE IF NOT EXISTS etl.pipeline_runs (
    run_id                 bigserial PRIMARY KEY,
    started_at             timestamptz NOT NULL DEFAULT now(),
    finished_at            timestamptz,
    status                 text        NOT NULL DEFAULT 'running'
                           CHECK (status IN ('running', 'success', 'failed')),
    source                 text        NOT NULL,
    window_start           timestamptz,
    updated_after          timestamptz,
    fetched                integer,
    valid                  integer,
    duplicates             integer,
    inserted               integer,
    updated                integer,
    unchanged              integer,
    rejected               integer,
    max_source_updated_at  timestamptz,
    error_message          text
);

-- Landing zone: untouched source payloads, kept for audit and reprocessing.
CREATE TABLE IF NOT EXISTS raw.usgs_events (
    raw_id             bigserial PRIMARY KEY,
    run_id             bigint      NOT NULL REFERENCES etl.pipeline_runs (run_id),
    event_id           text,
    source_updated_at  timestamptz,
    payload            jsonb       NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, source_updated_at)
);

-- Curated table: one row per earthquake, always holding the latest revision.
CREATE TABLE IF NOT EXISTS core.earthquakes (
    event_id           text PRIMARY KEY,
    occurred_at        timestamptz      NOT NULL,
    source_updated_at  timestamptz      NOT NULL,
    magnitude          numeric(4, 2)    NOT NULL,
    magnitude_type     text,
    place              text,
    region             text,
    latitude           double precision NOT NULL CHECK (latitude  BETWEEN -90  AND 90),
    longitude          double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    depth_km           double precision,
    event_type         text,
    review_status      text,
    tsunami_flag       boolean          NOT NULL DEFAULT false,
    significance       integer,
    felt_reports       integer,
    detail_url         text,
    first_loaded_at    timestamptz      NOT NULL DEFAULT now(),
    last_loaded_at     timestamptz      NOT NULL DEFAULT now(),
    run_id             bigint           NOT NULL REFERENCES etl.pipeline_runs (run_id)
);

CREATE INDEX IF NOT EXISTS ix_earthquakes_occurred_at ON core.earthquakes (occurred_at);
CREATE INDEX IF NOT EXISTS ix_earthquakes_region      ON core.earthquakes (region);

-- Records that failed data-quality checks, with the reasons, so nothing is
-- silently dropped.
CREATE TABLE IF NOT EXISTS core.rejected_events (
    rejected_id  bigserial PRIMARY KEY,
    run_id       bigint      NOT NULL REFERENCES etl.pipeline_runs (run_id),
    event_id     text,
    reasons      text[]      NOT NULL,
    payload      jsonb       NOT NULL,
    rejected_at  timestamptz NOT NULL DEFAULT now()
);

-- The same bad record re-read in an overlapping window is stored only once.
CREATE UNIQUE INDEX IF NOT EXISTS ux_rejected_events_version
    ON core.rejected_events ((coalesce(event_id, '')), (md5(payload::text)));
