"""
S.T.R.A.N.D — Tests: Database Schema, Connection & Queries

Tests DuckDB connection handling, idempotent schema initialization,
pipeline phase logging, warnings recording, and spatial query functions.
"""

from __future__ import annotations

import duckdb
import pytest

from strand.db.connection import check_db_health, close_db, get_db
from strand.db.migrations import SCHEMA_SQL, run_migrations
from strand.db.spatial_queries import (
    _wkt_to_geojson_geometry,
    add_analysis_warning,
    get_analysis_summary,
    get_analysis_warnings,
    log_pipeline_phase,
)


class TestDatabaseConnection:
    """Test DuckDB singleton and connection lifecycle."""

    def test_connection_singleton(self):
        conn1 = get_db()
        conn2 = get_db()
        assert conn1 is conn2

    def test_health_check(self):
        status = check_db_health()
        assert status == "connected"

    def test_close_and_reopen(self):
        close_db()
        conn = get_db()
        assert conn is not None
        assert check_db_health() == "connected"


class TestDatabaseMigrations:
    """Test idempotent schema migration execution."""

    def test_schema_sql_defined(self):
        assert isinstance(SCHEMA_SQL, str)
        assert "CREATE TABLE IF NOT EXISTS analyses" in SCHEMA_SQL
        assert "CREATE TABLE IF NOT EXISTS flood_polygons" in SCHEMA_SQL
        assert "CREATE TABLE IF NOT EXISTS road_segments" in SCHEMA_SQL

    def test_migrations_run_without_error(self):
        run_migrations()

    def test_migrations_are_idempotent(self):
        run_migrations()
        run_migrations()  # Running twice should not throw duplicate table error


class TestSpatialQueriesAndLogging:
    """Test database helper queries, logging, and warnings."""

    def test_log_pipeline_phase(self, analysis_id):
        conn = get_db()
        # Insert minimal analysis row
        conn.execute(
            """
            INSERT OR REPLACE INTO analyses (id, aoi_bbox, disaster_date, utm_zone, utm_epsg)
            VALUES (?, '85.8,27.7,86.0,27.9', '2026-08-26', 45, 32645)
            """,
            [analysis_id],
        )

        log_pipeline_phase(analysis_id, "sar_preprocessing", 25.0)

        row = get_analysis_summary(analysis_id)
        assert row is not None
        assert row["current_phase"] == "sar_preprocessing"
        assert row["progress_pct"] == 25.0

    def test_warnings_logging(self, analysis_id):
        add_analysis_warning(analysis_id, "Cloud cover exceeds 20%")
        add_analysis_warning(analysis_id, "OSM roads incomplete in northern quadrant")

        warnings = get_analysis_warnings(analysis_id)
        assert len(warnings) >= 2
        assert any("Cloud cover" in w for w in warnings)
        assert any("OSM roads" in w for w in warnings)

    def test_wkt_to_geojson_geometry(self):
        point_wkt = "POINT(85.85 27.85)"
        geom = _wkt_to_geojson_geometry(point_wkt)
        assert geom is not None
        assert geom["type"] == "Point"
        assert len(geom["coordinates"]) == 2
        assert geom["coordinates"][0] == 85.85
        assert geom["coordinates"][1] == 27.85

        polygon_wkt = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
        poly_geom = _wkt_to_geojson_geometry(polygon_wkt)
        assert poly_geom is not None
        assert poly_geom["type"] == "Polygon"

    def test_empty_wkt_handling(self):
        assert _wkt_to_geojson_geometry(None) is None
        assert _wkt_to_geojson_geometry("") is None
