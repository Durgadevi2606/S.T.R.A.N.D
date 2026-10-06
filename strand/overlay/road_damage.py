"""
S.T.R.A.N.D — Road Damage Assessment

Classifies road segments by spatial intersection with flood polygons.
Each road segment is classified as:
- INTACT: No flood intersection (intersection_ratio = 0)
- PARTIALLY_FLOODED: 1–50% of length flooded
- SEVERED: >50% of length flooded (impassable)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import geopandas as gpd
from shapely.geometry import shape

from strand.config import ROAD_PARTIAL_FLOOD_THRESHOLD, ROAD_SEVERED_THRESHOLD

logger = logging.getLogger(__name__)


def classify_road_damage(
    roads_gdf: gpd.GeoDataFrame,
    flood_gdf: gpd.GeoDataFrame,
    partial_threshold: float = ROAD_PARTIAL_FLOOD_THRESHOLD,
    severed_threshold: float = ROAD_SEVERED_THRESHOLD,
) -> gpd.GeoDataFrame:
    """
    Classify road segments based on spatial intersection with flood polygons.

    Algorithm:
    1. For each road segment, compute the geometric intersection with flood polygons
    2. Calculate the ratio: intersected_length / total_length
    3. Classify based on thresholds:
       - ratio == 0 → INTACT
       - 0 < ratio ≤ 0.50 → PARTIALLY_FLOODED
       - ratio > 0.50 → SEVERED

    Args:
        roads_gdf: GeoDataFrame of road LineString geometries.
        flood_gdf: GeoDataFrame of flood Polygon geometries.
        partial_threshold: Min ratio for partial flooding (default 0.01 = 1%).
        severed_threshold: Min ratio for severed (default 0.50 = 50%).

    Returns:
        GeoDataFrame with added columns:
        - damage_class: 'intact', 'partially_flooded', or 'severed'
        - flood_intersection_ratio: 0.0 to 1.0
        - length_m: Total segment length in meters
    """
    logger.info(
        "Classifying road damage: %d roads vs %d flood polygons",
        len(roads_gdf), len(flood_gdf),
    )

    if roads_gdf.empty:
        logger.warning("No road segments to classify")
        return roads_gdf

    # Ensure same CRS
    if roads_gdf.crs != flood_gdf.crs and not flood_gdf.empty:
        flood_gdf = flood_gdf.to_crs(roads_gdf.crs)

    # Compute road lengths
    if "length_m" not in roads_gdf.columns:
        roads_gdf = roads_gdf.copy()
        roads_gdf["length_m"] = roads_gdf.geometry.length

    # Union all flood polygons for efficient intersection
    if flood_gdf.empty:
        roads_gdf["flood_intersection_ratio"] = 0.0
        roads_gdf["damage_class"] = "intact"
        logger.info("No flood polygons — all roads classified as intact")
        return roads_gdf

    flood_union = flood_gdf.geometry.unary_union

    # Classify each road
    ratios = []
    classes = []

    for idx, road in roads_gdf.iterrows():
        try:
            road_geom = road.geometry
            road_length = road.length_m if road.length_m > 0 else road_geom.length

            if road_length == 0:
                ratios.append(0.0)
                classes.append("intact")
                continue

            intersection = road_geom.intersection(flood_union)

            if intersection.is_empty:
                ratio = 0.0
            else:
                ratio = intersection.length / road_length

            ratio = min(ratio, 1.0)  # Clamp to [0, 1]
            ratios.append(ratio)

            if ratio >= severed_threshold:
                classes.append("severed")
            elif ratio >= partial_threshold:
                classes.append("partially_flooded")
            else:
                classes.append("intact")

        except Exception as e:
            logger.warning("Road classification failed for segment %s: %s", idx, e)
            ratios.append(0.0)
            classes.append("intact")

    roads_gdf = roads_gdf.copy()
    roads_gdf["flood_intersection_ratio"] = ratios
    roads_gdf["damage_class"] = classes

    # Statistics
    intact = sum(1 for c in classes if c == "intact")
    partial = sum(1 for c in classes if c == "partially_flooded")
    severed = sum(1 for c in classes if c == "severed")

    logger.info(
        "Road damage classification: %d intact, %d partially flooded, %d severed",
        intact, partial, severed,
    )

    return roads_gdf
