"""
S.T.R.A.N.D — Database Schema Migrations

Creates all tables in the DuckDB spatial database.
Idempotent — safe to run multiple times (uses IF NOT EXISTS).
"""

from __future__ import annotations

import logging

import duckdb

from strand.db.connection import get_db

logger = logging.getLogger(__name__)


# ─── Schema DDL ──────────────────────────────────────────────

SCHEMA_SQL = """
-- =============================================================
-- S.T.R.A.N.D Database Schema
-- DuckDB with Spatial Extension
-- =============================================================

-- Master analysis table
CREATE TABLE IF NOT EXISTS analyses (
    id                   VARCHAR PRIMARY KEY,
    aoi_bbox             VARCHAR NOT NULL,
    disaster_date        DATE NOT NULL,
    utm_zone             INTEGER NOT NULL,
    utm_epsg             INTEGER NOT NULL,
    s1_orbit_number      INTEGER,
    sar_pre_product      VARCHAR,
    sar_post_product     VARCHAR,
    sar_pre_date         DATE,
    sar_post_date        DATE,
    orbit_direction      VARCHAR,
    dem_product          VARCHAR,
    s2_product           VARCHAR,
    s2_available         BOOLEAN DEFAULT FALSE,
    osm_snapshot_ts      VARCHAR,
    status               VARCHAR DEFAULT 'queued',
    progress_pct         DOUBLE DEFAULT 0.0,
    current_phase        VARCHAR,
    flood_area_km2       DOUBLE,
    roads_total_km       DOUBLE,
    roads_severed_km     DOUBLE,
    roads_partial_km     DOUBLE,
    bridges_total        INTEGER,
    bridges_destroyed    INTEGER,
    bridges_damaged      INTEGER,
    buildings_total      INTEGER,
    buildings_submerged  INTEGER,
    buildings_contact    INTEGER,
    settlements_total    INTEGER,
    settlements_isolated INTEGER,
    settlements_degraded INTEGER,
    hlz_count            INTEGER,
    ponding_count        INTEGER,
    created_at           TIMESTAMP DEFAULT current_timestamp,
    completed_at         TIMESTAMP
);

-- Flood extent polygons
CREATE TABLE IF NOT EXISTS flood_polygons (
    id               VARCHAR PRIMARY KEY,
    analysis_id      VARCHAR NOT NULL,
    geom_wkt         VARCHAR NOT NULL,
    area_m2          DOUBLE NOT NULL,
    confidence       DOUBLE,
    detection_method VARCHAR,
    mndwi_validated  BOOLEAN DEFAULT FALSE
);

-- Road segments with damage classification
CREATE TABLE IF NOT EXISTS road_segments (
    id                       VARCHAR PRIMARY KEY,
    analysis_id              VARCHAR NOT NULL,
    osm_id                   BIGINT,
    geom_wkt                 VARCHAR NOT NULL,
    highway_type             VARCHAR,
    name                     VARCHAR,
    length_m                 DOUBLE NOT NULL,
    damage_class             VARCHAR,
    flood_intersection_ratio DOUBLE,
    is_graph_edge            BOOLEAN DEFAULT TRUE
);

-- Bridge points/lines
CREATE TABLE IF NOT EXISTS bridges (
    id                  VARCHAR PRIMARY KEY,
    analysis_id         VARCHAR NOT NULL,
    osm_id              BIGINT,
    geom_wkt            VARCHAR NOT NULL,
    name                VARCHAR,
    damage_class        VARCHAR,
    buffer_flood_ratio  DOUBLE
);

-- Building footprints
CREATE TABLE IF NOT EXISTS buildings (
    id                       VARCHAR PRIMARY KEY,
    analysis_id              VARCHAR NOT NULL,
    osm_id                   BIGINT,
    geom_wkt                 VARCHAR NOT NULL,
    building_type            VARCHAR,
    damage_class             VARCHAR,
    flood_intersection_ratio DOUBLE
);

-- Settlement nodes
CREATE TABLE IF NOT EXISTS settlements (
    id                       VARCHAR PRIMARY KEY,
    analysis_id              VARCHAR NOT NULL,
    osm_id                   BIGINT,
    geom_wkt                 VARCHAR NOT NULL,
    name                     VARCHAR,
    place_type               VARCHAR,
    estimated_population     INTEGER,
    isolation_status         VARCHAR,
    urgency_score            DOUBLE,
    pre_disaster_hub_dist_m  DOUBLE,
    post_disaster_hub_dist_m DOUBLE,
    has_clinic               BOOLEAN DEFAULT FALSE,
    nearest_hlz_id           VARCHAR
);

-- Hub nodes (hospitals, supply depots)
CREATE TABLE IF NOT EXISTS hub_nodes (
    id           VARCHAR PRIMARY KEY,
    analysis_id  VARCHAR NOT NULL,
    osm_id       BIGINT,
    geom_wkt     VARCHAR NOT NULL,
    name         VARCHAR,
    hub_type     VARCHAR,
    amenity_type VARCHAR
);

-- Routes between settlements and hubs
CREATE TABLE IF NOT EXISTS settlement_hub_routes (
    id                   VARCHAR PRIMARY KEY,
    settlement_id        VARCHAR NOT NULL,
    hub_id               VARCHAR NOT NULL,
    pre_disaster_dist_m  DOUBLE,
    post_disaster_dist_m DOUBLE,
    is_reachable         BOOLEAN,
    pre_route_wkt        VARCHAR,
    post_route_wkt       VARCHAR
);

-- Helicopter Landing Zones
CREATE TABLE IF NOT EXISTS hlz_sites (
    id                    VARCHAR PRIMARY KEY,
    analysis_id           VARCHAR NOT NULL,
    geom_wkt              VARCHAR NOT NULL,
    centroid_wkt          VARCHAR NOT NULL,
    area_m2               DOUBLE NOT NULL,
    avg_slope_deg         DOUBLE NOT NULL,
    max_slope_deg         DOUBLE,
    elevation_m           DOUBLE NOT NULL,
    nearest_settlement_id VARCHAR,
    dist_to_settlement_m  DOUBLE,
    surface_estimate      VARCHAR
);

-- Ponding / debris dam zones
CREATE TABLE IF NOT EXISTS ponding_zones (
    id                  VARCHAR PRIMARY KEY,
    analysis_id         VARCHAR NOT NULL,
    geom_wkt            VARCHAR NOT NULL,
    area_m2             DOUBLE NOT NULL,
    estimated_volume_m3 DOUBLE,
    dam_elevation_m     DOUBLE,
    risk_level          VARCHAR,
    downstream_wkt      VARCHAR
);

-- D8 flow paths
CREATE TABLE IF NOT EXISTS flow_paths (
    id                      VARCHAR PRIMARY KEY,
    analysis_id             VARCHAR NOT NULL,
    origin_wkt              VARCHAR NOT NULL,
    path_wkt                VARCHAR NOT NULL,
    total_length_m          DOUBLE,
    total_drop_m            DOUBLE,
    settlements_intersected INTEGER DEFAULT 0
);

-- Pipeline execution logs
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id           VARCHAR PRIMARY KEY,
    analysis_id  VARCHAR NOT NULL,
    phase        VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,
    message      VARCHAR,
    progress_pct DOUBLE,
    logged_at    TIMESTAMP DEFAULT current_timestamp
);

-- Copilot query audit log
CREATE TABLE IF NOT EXISTS copilot_queries (
    id                  VARCHAR PRIMARY KEY,
    analysis_id         VARCHAR NOT NULL,
    user_query          VARCHAR NOT NULL,
    language            VARCHAR,
    generated_sql       VARCHAR,
    response_text       VARCHAR,
    hallucination_check BOOLEAN DEFAULT TRUE,
    queried_at          TIMESTAMP DEFAULT current_timestamp
);

-- Warnings table for analysis
CREATE TABLE IF NOT EXISTS analysis_warnings (
    id          VARCHAR PRIMARY KEY,
    analysis_id VARCHAR NOT NULL,
    message     VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT current_timestamp
);
"""


def run_migrations() -> None:
    """
    Execute all schema creation statements.

    Idempotent — safe to call on every application startup.
    Uses IF NOT EXISTS for all table definitions.
    """
    conn = get_db()

    logger.info("Running database migrations...")

    # Split and execute each statement separately
    # DuckDB handles multi-statement strings, but splitting gives better error reporting
    statements = [s.strip() for s in SCHEMA_SQL.split(";") if s.strip()]
    executed_count = 0
    for i, stmt in enumerate(statements):
        sql_lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
        clean_stmt = "\n".join(sql_lines).strip()
        if not clean_stmt:
            continue
        try:
            conn.execute(clean_stmt + ";")
            executed_count += 1
        except Exception as e:
            logger.error("Migration statement %d failed: %s\nSQL: %s", i, e, clean_stmt[:200])
            raise

    logger.info("Database migrations complete — %d statements executed", executed_count)


def drop_all_tables() -> None:
    """
    Drop all S.T.R.A.N.D tables. USE WITH EXTREME CAUTION.

    This is only for development/testing. Never call in production.
    """
    conn = get_db()
    tables = [
        "analysis_warnings",
        "copilot_queries",
        "pipeline_logs",
        "flow_paths",
        "ponding_zones",
        "hlz_sites",
        "settlement_hub_routes",
        "hub_nodes",
        "settlements",
        "buildings",
        "bridges",
        "road_segments",
        "flood_polygons",
        "analyses",
    ]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table};")
    logger.warning("All tables dropped")
