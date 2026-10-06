"""
S.T.R.A.N.D — Helicopter Landing Zone (HLZ) Finder

Identifies safe, flat terrain suitable for helicopter landing using:
1. DEM slope analysis (slope ≤ 5°)
2. Minimum contiguous flat area (≥ 900 m² = 30m × 30m)
3. Exclusion zones: flood extent, forests, power lines
4. Proximity ranking to isolated settlements

Criteria based on US Army FM 3-04.203 helicopter landing zone standards.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from scipy import ndimage
from shapely.geometry import Point, box, mapping, shape

from strand.config import (
    HLZ_MAX_ELEVATION_M,
    HLZ_MAX_SLOPE_DEG,
    HLZ_MIN_AREA_M2,
)

logger = logging.getLogger(__name__)


def compute_slope(dem_path: Path) -> tuple[np.ndarray, dict]:
    """
    Compute slope in degrees from a DEM GeoTIFF.

    Uses numpy gradient (finite-difference approximation of
    partial derivatives ∂z/∂x and ∂z/∂y).

    Args:
        dem_path: Path to DEM GeoTIFF in projected CRS (meters).

    Returns:
        Tuple of (slope_degrees_array, raster_metadata).
    """
    with rasterio.open(dem_path) as ds:
        dem = ds.read(1).astype(np.float32)
        pixel_size = abs(ds.transform.a)
        meta = {
            "transform": ds.transform,
            "crs": ds.crs,
            "width": ds.width,
            "height": ds.height,
            "bounds": ds.bounds,
        }

    # Fill nodata with interpolation
    dem = np.where(np.isfinite(dem), dem, np.nanmean(dem))

    # Compute gradient
    dy, dx = np.gradient(dem, pixel_size)
    slope_rad = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    slope_deg = np.degrees(slope_rad)

    logger.info(
        "Slope computed: min=%.1f°, max=%.1f°, mean=%.1f°",
        np.nanmin(slope_deg), np.nanmax(slope_deg), np.nanmean(slope_deg),
    )

    return slope_deg, meta


def find_flat_areas(
    slope_deg: np.ndarray,
    dem_array: np.ndarray,
    raster_meta: dict,
    max_slope: float = HLZ_MAX_SLOPE_DEG,
    min_area_m2: float = HLZ_MIN_AREA_M2,
    max_elevation_m: float = HLZ_MAX_ELEVATION_M,
) -> list[dict[str, Any]]:
    """
    Extract connected flat regions suitable for helicopter landing.

    Algorithm:
    1. Create binary mask: slope ≤ max_slope AND elevation ≤ max_elevation
    2. Label connected components
    3. Filter by minimum area
    4. Extract polygon geometry, centroid, and statistics

    Args:
        slope_deg: Slope array in degrees.
        dem_array: Elevation array in meters.
        raster_meta: Raster metadata (transform, CRS).
        max_slope: Maximum acceptable slope (degrees).
        min_area_m2: Minimum contiguous flat area (m²).
        max_elevation_m: Maximum elevation for HLZ.

    Returns:
        List of HLZ candidate dicts with geometry and properties.
    """
    pixel_size = abs(raster_meta["transform"].a)
    pixel_area = pixel_size ** 2
    min_pixels = int(min_area_m2 / pixel_area)

    # Create flat mask
    flat_mask = (slope_deg <= max_slope) & (dem_array <= max_elevation_m)
    flat_mask = flat_mask & np.isfinite(slope_deg)

    # Label connected components
    labeled, n_components = ndimage.label(flat_mask)
    logger.info(
        "Found %d connected flat regions (slope ≤ %.1f°)", n_components, max_slope
    )

    # Filter by area and extract properties
    candidates = []
    transform = raster_meta["transform"]

    for label_id in range(1, n_components + 1):
        component_mask = labeled == label_id
        pixel_count = component_mask.sum()

        if pixel_count < min_pixels:
            continue

        area_m2 = pixel_count * pixel_area

        # Compute statistics
        component_slopes = slope_deg[component_mask]
        component_elevations = dem_array[component_mask]

        avg_slope = float(np.nanmean(component_slopes))
        max_slope_val = float(np.nanmax(component_slopes))
        avg_elevation = float(np.nanmean(component_elevations))

        # Compute centroid in pixel coordinates
        rows, cols = np.where(component_mask)
        center_row = int(np.mean(rows))
        center_col = int(np.mean(cols))

        # Convert to geographic coordinates
        center_x, center_y = rasterio.transform.xy(
            transform, center_row, center_col
        )

        # Compute bounding box for the region
        min_row, max_row = rows.min(), rows.max()
        min_col, max_col = cols.min(), cols.max()

        ul_x, ul_y = rasterio.transform.xy(transform, min_row, min_col)
        lr_x, lr_y = rasterio.transform.xy(transform, max_row, max_col)

        # Estimate surface type based on elevation and slope
        surface = _estimate_surface(avg_elevation, avg_slope)

        candidate = {
            "id": str(uuid.uuid4()),
            "centroid_x": center_x,
            "centroid_y": center_y,
            "area_m2": round(area_m2, 1),
            "avg_slope_deg": round(avg_slope, 2),
            "max_slope_deg": round(max_slope_val, 2),
            "elevation_m": round(avg_elevation, 1),
            "surface_estimate": surface,
            "bbox": [ul_x, ul_y, lr_x, lr_y],
            "pixel_count": pixel_count,
        }
        candidates.append(candidate)

    # Sort by area (largest first)
    candidates.sort(key=lambda c: c["area_m2"], reverse=True)

    logger.info(
        "HLZ candidates after area filter (≥%.0f m²): %d",
        min_area_m2, len(candidates),
    )

    return candidates


def apply_exclusion_zones(
    candidates: list[dict],
    flood_gdf: gpd.GeoDataFrame,
    forest_gdf: gpd.GeoDataFrame | None = None,
    power_line_gdf: gpd.GeoDataFrame | None = None,
    buffer_m: float = 100.0,
) -> list[dict]:
    """
    Remove HLZ candidates that overlap exclusion zones.

    Exclusions:
    - Flood extent (can't land in water)
    - Forest/woodland (tree obstruction)
    - Power lines (safety hazard, 100m buffer)

    Args:
        candidates: List of HLZ candidate dicts.
        flood_gdf: Flood polygon GeoDataFrame.
        forest_gdf: Optional forest polygon GeoDataFrame.
        power_line_gdf: Optional power line LineString GeoDataFrame.
        buffer_m: Buffer around exclusion features (meters).

    Returns:
        Filtered list of safe HLZ candidates.
    """
    if not candidates:
        return candidates

    # Build exclusion geometry
    exclusion_parts = []

    if not flood_gdf.empty:
        flood_union = flood_gdf.geometry.buffer(buffer_m).unary_union
        exclusion_parts.append(flood_union)

    if forest_gdf is not None and not forest_gdf.empty:
        forest_union = forest_gdf.geometry.unary_union
        exclusion_parts.append(forest_union)

    if power_line_gdf is not None and not power_line_gdf.empty:
        power_buffer = power_line_gdf.geometry.buffer(buffer_m).unary_union
        exclusion_parts.append(power_buffer)

    if not exclusion_parts:
        return candidates

    from shapely.ops import unary_union
    exclusion_zone = unary_union(exclusion_parts)

    # Filter candidates
    safe_candidates = []
    excluded_count = 0

    for candidate in candidates:
        centroid = Point(candidate["centroid_x"], candidate["centroid_y"])

        if exclusion_zone.contains(centroid):
            excluded_count += 1
            continue

        safe_candidates.append(candidate)

    logger.info(
        "Exclusion filtering: %d → %d candidates (%d excluded)",
        len(candidates), len(safe_candidates), excluded_count,
    )

    return safe_candidates


def rank_by_settlement_proximity(
    candidates: list[dict],
    settlements_gdf: gpd.GeoDataFrame,
) -> list[dict]:
    """
    Rank HLZ candidates by proximity to isolated settlements.

    Assigns each HLZ to its nearest settlement and computes distance.

    Args:
        candidates: List of HLZ candidate dicts.
        settlements_gdf: GeoDataFrame of settlements (preferably isolated ones).

    Returns:
        Candidates with added nearest_settlement_id and distance fields.
    """
    if not candidates or settlements_gdf.empty:
        return candidates

    for candidate in candidates:
        centroid = Point(candidate["centroid_x"], candidate["centroid_y"])

        min_dist = float("inf")
        nearest_id = None

        for idx, settlement in settlements_gdf.iterrows():
            dist = centroid.distance(settlement.geometry)
            if dist < min_dist:
                min_dist = dist
                nearest_id = settlement.get("id", str(idx))

        candidate["nearest_settlement_id"] = nearest_id
        candidate["dist_to_settlement_m"] = round(min_dist, 1)

    # Sort by distance to nearest settlement (closest first)
    candidates.sort(key=lambda c: c.get("dist_to_settlement_m", float("inf")))

    return candidates


def run_hlz_finder(
    dem_path: Path,
    flood_gdf: gpd.GeoDataFrame,
    settlements_gdf: gpd.GeoDataFrame,
    forest_gdf: gpd.GeoDataFrame | None = None,
    power_line_gdf: gpd.GeoDataFrame | None = None,
    max_slope: float = HLZ_MAX_SLOPE_DEG,
    min_area_m2: float = HLZ_MIN_AREA_M2,
) -> list[dict]:
    """
    Full HLZ finding pipeline.

    1. Compute slope from DEM
    2. Find flat areas meeting criteria
    3. Apply exclusion zones
    4. Rank by proximity to isolated settlements

    Args:
        dem_path: Path to UTM-projected DEM GeoTIFF.
        flood_gdf: Flood polygon GeoDataFrame.
        settlements_gdf: Isolated settlement GeoDataFrame.
        forest_gdf: Optional forest polygon GeoDataFrame.
        power_line_gdf: Optional power line GeoDataFrame.

    Returns:
        List of ranked HLZ candidate dicts.
    """
    logger.info("=" * 50)
    logger.info("HLZ FINDER — Starting")
    logger.info("=" * 50)

    # Step 1: Compute slope
    slope_deg, meta = compute_slope(dem_path)

    # Read DEM for elevation filtering
    with rasterio.open(dem_path) as ds:
        dem_array = ds.read(1).astype(np.float32)

    # Step 2: Find flat areas
    candidates = find_flat_areas(
        slope_deg, dem_array, meta,
        max_slope=max_slope, min_area_m2=min_area_m2,
    )

    # Step 3: Exclusion zones
    candidates = apply_exclusion_zones(
        candidates, flood_gdf, forest_gdf, power_line_gdf
    )

    # Step 4: Rank by settlement proximity
    candidates = rank_by_settlement_proximity(candidates, settlements_gdf)

    logger.info("HLZ FINDER complete: %d candidates identified", len(candidates))

    return candidates


def _estimate_surface(elevation_m: float, avg_slope_deg: float) -> str:
    """Estimate landing surface type based on elevation and terrain."""
    if elevation_m > 4000:
        return "rock/gravel (high altitude)"
    elif elevation_m > 3000:
        return "alpine meadow"
    elif avg_slope_deg < 2:
        return "flat ground (possible terrace/field)"
    else:
        return "gentle slope"
