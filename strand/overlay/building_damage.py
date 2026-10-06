"""
S.T.R.A.N.D — Building Damage Assessment

Classifies building footprints by flood polygon intersection.

Classification:
- SAFE: No flood contact
- FLOOD_CONTACT: 1–30% of footprint area flooded
- SUBMERGED: ≥30% of footprint area flooded
"""

from __future__ import annotations

import logging

import geopandas as gpd

from strand.config import (
    BUILDING_FLOOD_CONTACT_THRESHOLD,
    BUILDING_SUBMERGED_THRESHOLD,
    NEPAL_AVG_HOUSEHOLD_SIZE,
)

logger = logging.getLogger(__name__)


def classify_building_damage(
    buildings_gdf: gpd.GeoDataFrame,
    flood_gdf: gpd.GeoDataFrame,
    contact_threshold: float = BUILDING_FLOOD_CONTACT_THRESHOLD,
    submerged_threshold: float = BUILDING_SUBMERGED_THRESHOLD,
) -> gpd.GeoDataFrame:
    """
    Classify building damage based on flood footprint intersection.

    Args:
        buildings_gdf: GeoDataFrame of building Polygon geometries.
        flood_gdf: GeoDataFrame of flood Polygon geometries.
        contact_threshold: Min ratio for flood contact (default 1%).
        submerged_threshold: Min ratio for submerged (default 30%).

    Returns:
        GeoDataFrame with damage_class and flood_intersection_ratio columns.
    """
    logger.info(
        "Classifying building damage: %d buildings vs %d flood polygons",
        len(buildings_gdf), len(flood_gdf),
    )

    if buildings_gdf.empty:
        logger.warning("No buildings to classify")
        return buildings_gdf

    # Ensure same CRS
    if not flood_gdf.empty and buildings_gdf.crs != flood_gdf.crs:
        flood_gdf = flood_gdf.to_crs(buildings_gdf.crs)

    buildings_gdf = buildings_gdf.copy()

    if flood_gdf.empty:
        buildings_gdf["flood_intersection_ratio"] = 0.0
        buildings_gdf["damage_class"] = "safe"
        return buildings_gdf

    flood_union = flood_gdf.geometry.unary_union

    ratios = []
    classes = []

    for idx, bldg in buildings_gdf.iterrows():
        try:
            bldg_geom = bldg.geometry
            bldg_area = bldg_geom.area

            if bldg_area == 0:
                ratios.append(0.0)
                classes.append("safe")
                continue

            intersection = bldg_geom.intersection(flood_union)
            ratio = intersection.area / bldg_area if not intersection.is_empty else 0.0
            ratio = min(ratio, 1.0)

            ratios.append(ratio)

            if ratio >= submerged_threshold:
                classes.append("submerged")
            elif ratio >= contact_threshold:
                classes.append("flood_contact")
            else:
                classes.append("safe")

        except Exception as e:
            logger.warning("Building classification failed for %s: %s", idx, e)
            ratios.append(0.0)
            classes.append("safe")

    buildings_gdf["flood_intersection_ratio"] = ratios
    buildings_gdf["damage_class"] = classes

    safe = sum(1 for c in classes if c == "safe")
    contact = sum(1 for c in classes if c == "flood_contact")
    submerged = sum(1 for c in classes if c == "submerged")

    logger.info(
        "Building damage: %d safe, %d flood-contact, %d submerged",
        safe, contact, submerged,
    )

    return buildings_gdf


def estimate_affected_population(
    buildings_gdf: gpd.GeoDataFrame,
    avg_household_size: float = NEPAL_AVG_HOUSEHOLD_SIZE,
) -> dict[str, int]:
    """
    Estimate affected population based on damaged building count.

    Uses Nepal average household size (4.5 persons per building)
    as a proxy when census data is unavailable.

    Args:
        buildings_gdf: GeoDataFrame with damage_class column.
        avg_household_size: Average persons per building.

    Returns:
        Dict with population estimates by damage class.
    """
    if "damage_class" not in buildings_gdf.columns:
        return {"affected": 0, "submerged": 0, "contact": 0}

    submerged = (buildings_gdf["damage_class"] == "submerged").sum()
    contact = (buildings_gdf["damage_class"] == "flood_contact").sum()
    affected = submerged + contact

    result = {
        "affected_buildings": int(affected),
        "affected_population": int(affected * avg_household_size),
        "submerged_buildings": int(submerged),
        "submerged_population": int(submerged * avg_household_size),
        "contact_buildings": int(contact),
        "contact_population": int(contact * avg_household_size),
    }

    logger.info(
        "Population estimate: %d affected buildings → ~%d people",
        result["affected_buildings"], result["affected_population"],
    )

    return result
