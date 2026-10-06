"""
S.T.R.A.N.D — Reusable Spatial SQL Query Helpers

Provides parameterized query builders for common spatial operations
against the DuckDB spatial database. Used by the API layer, copilot,
and report generator.
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb

from strand.db.connection import get_db

logger = logging.getLogger(__name__)


def get_analysis_summary(analysis_id: str) -> dict[str, Any] | None:
    """Fetch the full summary row for an analysis."""
    conn = get_db()
    result = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", [analysis_id]
    ).fetchone()
    if result is None:
        return None
    columns = [desc[0] for desc in conn.description]
    return dict(zip(columns, result))


def get_flood_polygons_geojson(
    analysis_id: str,
    min_confidence: float = 0.0,
    simplify_m: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Fetch flood polygons as GeoJSON-ready dicts.

    Args:
        analysis_id: The analysis run ID.
        min_confidence: Minimum confidence filter (0.0–1.0).
        simplify_m: Douglas-Peucker simplification tolerance in meters.

    Returns:
        List of GeoJSON Feature dicts.
    """
    conn = get_db()

    geom_expr = "geom_wkt"
    if simplify_m > 0:
        geom_expr = f"ST_AsText(ST_SimplifyPreserveTopology(ST_GeomFromText(geom_wkt), {simplify_m}))"

    query = f"""
        SELECT
            id,
            {geom_expr} AS geometry_wkt,
            area_m2,
            area_m2 / 1e6 AS area_km2,
            confidence,
            detection_method,
            mndwi_validated
        FROM flood_polygons
        WHERE analysis_id = ?
          AND (confidence >= ? OR confidence IS NULL)
        ORDER BY area_m2 DESC
    """
    rows = conn.execute(query, [analysis_id, min_confidence]).fetchall()
    columns = [desc[0] for desc in conn.description]

    features = []
    for row in rows:
        row_dict = dict(zip(columns, row))
        features.append({
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(row_dict["geometry_wkt"]),
            "properties": {
                "id": row_dict["id"],
                "area_m2": row_dict["area_m2"],
                "area_km2": round(row_dict["area_km2"], 4),
                "confidence": row_dict["confidence"],
                "detection_method": row_dict["detection_method"],
                "mndwi_validated": row_dict["mndwi_validated"],
            },
        })
    return features


def get_road_segments_geojson(
    analysis_id: str,
    damage_class: str | None = None,
    highway_type: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch road segments as GeoJSON-ready dicts with optional filtering."""
    conn = get_db()
    conditions = ["analysis_id = ?"]
    params: list[Any] = [analysis_id]

    if damage_class and damage_class != "all":
        conditions.append("damage_class = ?")
        params.append(damage_class)
    if highway_type and highway_type != "all":
        conditions.append("highway_type = ?")
        params.append(highway_type)

    where = " AND ".join(conditions)
    query = f"""
        SELECT id, osm_id, geom_wkt, highway_type, name,
               length_m, damage_class, flood_intersection_ratio
        FROM road_segments
        WHERE {where}
        ORDER BY length_m DESC
    """
    rows = conn.execute(query, params).fetchall()
    columns = [desc[0] for desc in conn.description]

    return [
        {
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(dict(zip(columns, row))["geom_wkt"]),
            "properties": {
                k: v for k, v in dict(zip(columns, row)).items() if k != "geom_wkt"
            },
        }
        for row in rows
    ]


def get_settlements_geojson(
    analysis_id: str,
    isolation_status: str | None = None,
    sort_by: str = "urgency_score",
    sort_order: str = "desc",
) -> list[dict[str, Any]]:
    """Fetch settlements as GeoJSON-ready dicts with optional filtering."""
    conn = get_db()
    conditions = ["analysis_id = ?"]
    params: list[Any] = [analysis_id]

    if isolation_status and isolation_status != "all":
        conditions.append("isolation_status = ?")
        params.append(isolation_status)

    where = " AND ".join(conditions)

    # Whitelist sort columns to prevent SQL injection
    allowed_sorts = {"urgency_score", "estimated_population", "name"}
    if sort_by not in allowed_sorts:
        sort_by = "urgency_score"

    order_dir = "DESC" if sort_order.upper() == "DESC" else "ASC"

    query = f"""
        SELECT id, osm_id, geom_wkt, name, place_type,
               estimated_population, isolation_status, urgency_score,
               pre_disaster_hub_dist_m, post_disaster_hub_dist_m,
               has_clinic, nearest_hlz_id
        FROM settlements
        WHERE {where}
        ORDER BY {sort_by} {order_dir} NULLS LAST
    """
    rows = conn.execute(query, params).fetchall()
    columns = [desc[0] for desc in conn.description]

    return [
        {
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(dict(zip(columns, row))["geom_wkt"]),
            "properties": {
                k: v for k, v in dict(zip(columns, row)).items() if k != "geom_wkt"
            },
        }
        for row in rows
    ]


def get_hlz_sites_geojson(
    analysis_id: str,
    max_slope_deg: float = 5.0,
    min_area_m2: float = 900.0,
    sort_by: str = "dist_to_settlement_m",
) -> list[dict[str, Any]]:
    """Fetch HLZ sites as GeoJSON-ready dicts."""
    conn = get_db()
    query = """
        SELECT id, centroid_wkt, area_m2, avg_slope_deg, max_slope_deg,
               elevation_m, nearest_settlement_id, dist_to_settlement_m,
               surface_estimate
        FROM hlz_sites
        WHERE analysis_id = ?
          AND avg_slope_deg <= ?
          AND area_m2 >= ?
        ORDER BY dist_to_settlement_m ASC NULLS LAST
    """
    rows = conn.execute(query, [analysis_id, max_slope_deg, min_area_m2]).fetchall()
    columns = [desc[0] for desc in conn.description]

    return [
        {
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(
                dict(zip(columns, row))["centroid_wkt"]
            ),
            "properties": {
                k: v for k, v in dict(zip(columns, row)).items()
                if k != "centroid_wkt"
            },
        }
        for row in rows
    ]


def get_bridges_geojson(analysis_id: str, damage_class: str | None = None) -> list[dict]:
    """Fetch bridges as GeoJSON-ready dicts."""
    conn = get_db()
    conditions = ["analysis_id = ?"]
    params: list[Any] = [analysis_id]
    if damage_class and damage_class != "all":
        conditions.append("damage_class = ?")
        params.append(damage_class)
    where = " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT id, osm_id, geom_wkt, name, damage_class, buffer_flood_ratio "
        f"FROM bridges WHERE {where}", params
    ).fetchall()
    columns = [desc[0] for desc in conn.description]

    return [
        {
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(dict(zip(columns, row))["geom_wkt"]),
            "properties": {k: v for k, v in dict(zip(columns, row)).items() if k != "geom_wkt"},
        }
        for row in rows
    ]


def get_ponding_zones_geojson(analysis_id: str) -> list[dict]:
    """Fetch ponding zones as GeoJSON-ready dicts."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, geom_wkt, area_m2, estimated_volume_m3, dam_elevation_m, risk_level "
        "FROM ponding_zones WHERE analysis_id = ?", [analysis_id]
    ).fetchall()
    columns = [desc[0] for desc in conn.description]

    return [
        {
            "type": "Feature",
            "geometry": _wkt_to_geojson_geometry(dict(zip(columns, row))["geom_wkt"]),
            "properties": {k: v for k, v in dict(zip(columns, row)).items() if k != "geom_wkt"},
        }
        for row in rows
    ]


def log_pipeline_phase(
    analysis_id: str,
    phase: str,
    status: str,
    message: str = "",
    progress_pct: float = 0.0,
) -> None:
    """Insert a pipeline execution log entry."""
    import uuid as _uuid

    conn = get_db()
    conn.execute(
        """
        INSERT INTO pipeline_logs (id, analysis_id, phase, status, message, progress_pct)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [str(_uuid.uuid4()), analysis_id, phase, status, message, progress_pct],
    )


def get_analysis_warnings(analysis_id: str) -> list[str]:
    """Get all warnings for an analysis."""
    conn = get_db()
    rows = conn.execute(
        "SELECT message FROM analysis_warnings WHERE analysis_id = ? ORDER BY created_at",
        [analysis_id],
    ).fetchall()
    return [row[0] for row in rows]


def add_analysis_warning(analysis_id: str, message: str) -> None:
    """Add a warning to an analysis."""
    import uuid as _uuid

    conn = get_db()
    conn.execute(
        "INSERT INTO analysis_warnings (id, analysis_id, message) VALUES (?, ?, ?)",
        [str(_uuid.uuid4()), analysis_id, message],
    )


# ─── Aggregate Statistics ────────────────────────────────────

def compute_analysis_statistics(analysis_id: str) -> dict[str, Any]:
    """Compute and return all aggregate statistics for an analysis."""
    conn = get_db()

    stats: dict[str, Any] = {}

    # Flood area
    row = conn.execute(
        "SELECT COALESCE(SUM(area_m2) / 1e6, 0) FROM flood_polygons WHERE analysis_id = ?",
        [analysis_id],
    ).fetchone()
    stats["flood_area_km2"] = round(row[0], 2) if row else 0.0

    # Roads
    rows = conn.execute(
        """
        SELECT
            COALESCE(SUM(length_m) / 1000, 0) AS total_km,
            COALESCE(SUM(CASE WHEN damage_class = 'severed' THEN length_m ELSE 0 END) / 1000, 0) AS severed_km,
            COALESCE(SUM(CASE WHEN damage_class = 'partially_flooded' THEN length_m ELSE 0 END) / 1000, 0) AS partial_km
        FROM road_segments WHERE analysis_id = ?
        """,
        [analysis_id],
    ).fetchone()
    if rows:
        stats["roads_total_km"] = round(rows[0], 1)
        stats["roads_severed_km"] = round(rows[1], 1)
        stats["roads_partial_km"] = round(rows[2], 1)

    # Bridges
    rows = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN damage_class = 'destroyed' THEN 1 ELSE 0 END) AS destroyed,
            SUM(CASE WHEN damage_class = 'damaged' THEN 1 ELSE 0 END) AS damaged
        FROM bridges WHERE analysis_id = ?
        """,
        [analysis_id],
    ).fetchone()
    if rows:
        stats["bridges_total"] = rows[0]
        stats["bridges_destroyed"] = rows[1]
        stats["bridges_damaged"] = rows[2]

    # Buildings
    rows = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN damage_class = 'submerged' THEN 1 ELSE 0 END),
            SUM(CASE WHEN damage_class = 'flood_contact' THEN 1 ELSE 0 END)
        FROM buildings WHERE analysis_id = ?
        """,
        [analysis_id],
    ).fetchone()
    if rows:
        stats["buildings_total"] = rows[0]
        stats["buildings_submerged"] = rows[1]
        stats["buildings_contact"] = rows[2]

    # Settlements
    rows = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN isolation_status = 'isolated' THEN 1 ELSE 0 END),
            SUM(CASE WHEN isolation_status = 'degraded' THEN 1 ELSE 0 END)
        FROM settlements WHERE analysis_id = ?
        """,
        [analysis_id],
    ).fetchone()
    if rows:
        stats["settlements_total"] = rows[0]
        stats["settlements_isolated"] = rows[1]
        stats["settlements_degraded"] = rows[2]

    # HLZ
    row = conn.execute(
        "SELECT COUNT(*) FROM hlz_sites WHERE analysis_id = ?", [analysis_id]
    ).fetchone()
    stats["hlz_count"] = row[0] if row else 0

    # Ponding
    row = conn.execute(
        "SELECT COUNT(*) FROM ponding_zones WHERE analysis_id = ?", [analysis_id]
    ).fetchone()
    stats["ponding_count"] = row[0] if row else 0

    return stats


# ─── Utility ─────────────────────────────────────────────────

def _wkt_to_geojson_geometry(wkt: str | None) -> dict[str, Any] | None:
    """
    Convert a WKT geometry string to a GeoJSON geometry dict.

    Uses DuckDB spatial's ST_AsGeoJSON for proper conversion.
    Falls back to a simple POINT parser for basic cases.
    """
    if wkt is None:
        return None

    try:
        conn = get_db()
        result = conn.execute(
            "SELECT ST_AsGeoJSON(ST_GeomFromText(?))", [wkt]
        ).fetchone()
        if result and result[0]:
            import json
            return json.loads(result[0])
    except Exception:
        pass

    # Fallback: simple POINT parser
    if wkt.startswith("POINT"):
        import re
        match = re.search(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", wkt)
        if match:
            return {
                "type": "Point",
                "coordinates": [float(match.group(1)), float(match.group(2))],
            }

    return {"type": "GeometryCollection", "geometries": []}
