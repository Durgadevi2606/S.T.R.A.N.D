"""
S.T.R.A.N.D — Bridge Damage Assessment

Classifies bridges based on flood proximity using buffer analysis.
Each bridge gets a circular buffer, then we check flood overlap.

Classification:
- INTACT: No flood within buffer radius
- DAMAGED: Flood overlaps buffer but < 50% coverage
- DESTROYED: Flood covers ≥ 50% of buffer (likely swept away)
"""

from __future__ import annotations

import logging

import geopandas as gpd

from strand.config import BRIDGE_BUFFER_RADIUS_M

logger = logging.getLogger(__name__)


def classify_bridge_damage(
    bridges_gdf: gpd.GeoDataFrame,
    flood_gdf: gpd.GeoDataFrame,
    buffer_radius_m: float = BRIDGE_BUFFER_RADIUS_M,
    damaged_threshold: float = 0.01,
    destroyed_threshold: float = 0.50,
) -> gpd.GeoDataFrame:
    """
    Classify bridge damage based on flood proximity.

    Algorithm:
    1. Buffer each bridge point/line by buffer_radius_m
    2. Compute intersection area with flood polygons
    3. Classify: ratio of intersection / buffer area

    Args:
        bridges_gdf: GeoDataFrame of bridge geometries (Point or LineString).
        flood_gdf: GeoDataFrame of flood Polygon geometries.
        buffer_radius_m: Buffer radius around bridges (meters).
        damaged_threshold: Min flood/buffer ratio for 'damaged'.
        destroyed_threshold: Min flood/buffer ratio for 'destroyed'.

    Returns:
        GeoDataFrame with 'damage_class' and 'buffer_flood_ratio' columns.
    """
    logger.info(
        "Classifying bridge damage: %d bridges, buffer=%.0fm",
        len(bridges_gdf), buffer_radius_m,
    )

    if bridges_gdf.empty:
        logger.warning("No bridges to classify")
        return bridges_gdf

    # Ensure same CRS
    if not flood_gdf.empty and bridges_gdf.crs != flood_gdf.crs:
        flood_gdf = flood_gdf.to_crs(bridges_gdf.crs)

    bridges_gdf = bridges_gdf.copy()

    if flood_gdf.empty:
        bridges_gdf["buffer_flood_ratio"] = 0.0
        bridges_gdf["damage_class"] = "intact"
        return bridges_gdf

    flood_union = flood_gdf.geometry.unary_union

    ratios = []
    classes = []

    for idx, bridge in bridges_gdf.iterrows():
        try:
            # Buffer the bridge geometry
            buffer_geom = bridge.geometry.buffer(buffer_radius_m)
            buffer_area = buffer_geom.area

            if buffer_area == 0:
                ratios.append(0.0)
                classes.append("intact")
                continue

            # Compute flood intersection
            intersection = buffer_geom.intersection(flood_union)
            ratio = intersection.area / buffer_area if not intersection.is_empty else 0.0
            ratio = min(ratio, 1.0)

            ratios.append(ratio)

            if ratio >= destroyed_threshold:
                classes.append("destroyed")
            elif ratio >= damaged_threshold:
                classes.append("damaged")
            else:
                classes.append("intact")

        except Exception as e:
            logger.warning("Bridge classification failed for %s: %s", idx, e)
            ratios.append(0.0)
            classes.append("intact")

    bridges_gdf["buffer_flood_ratio"] = ratios
    bridges_gdf["damage_class"] = classes

    intact = sum(1 for c in classes if c == "intact")
    damaged = sum(1 for c in classes if c == "damaged")
    destroyed = sum(1 for c in classes if c == "destroyed")

    logger.info(
        "Bridge damage: %d intact, %d damaged, %d destroyed",
        intact, damaged, destroyed,
    )

    return bridges_gdf
