"""
S.T.R.A.N.D — Debris Dam Ponding Detector & D8 Flow-Path Tracer

Innovation module for upstream hazard detection:
1. Ponding detector: Identifies terrain depressions behind potential debris dams
   that could accumulate dangerous water volumes.
2. Flow tracer: Traces D8 (steepest descent) flow paths from the collapse
   origin to downstream settlements.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from scipy import ndimage

from strand.config import PONDING_VOLUME_THRESHOLD_M3

logger = logging.getLogger(__name__)


# ─── Ponding Detector ────────────────────────────────────────

def detect_ponding_zones(
    dem_path: Path,
    flood_mask: np.ndarray | None = None,
    volume_threshold_m3: float = PONDING_VOLUME_THRESHOLD_M3,
) -> list[dict[str, Any]]:
    """
    Detect potential ponding zones behind debris dams.

    Algorithm:
    1. Fill DEM depressions (pit removal)
    2. Compute difference: filled_DEM - original_DEM
    3. Regions with large depth difference = potential ponding areas
    4. Estimate ponding volume = Σ(depth × pixel_area)
    5. Assign risk level based on volume and downstream presence

    Args:
        dem_path: Path to UTM-projected DEM GeoTIFF.
        flood_mask: Optional binary flood mask (to focus on relevant areas).
        volume_threshold_m3: Minimum volume to report as a ponding zone.

    Returns:
        List of ponding zone dicts with geometry, volume, and risk level.
    """
    logger.info("Detecting ponding zones from DEM...")

    with rasterio.open(dem_path) as ds:
        dem = ds.read(1).astype(np.float32)
        pixel_size = abs(ds.transform.a)
        pixel_area = pixel_size ** 2
        transform = ds.transform
        crs = ds.crs

    # Step 1: Fill depressions using iterative filling
    filled_dem = _fill_depressions(dem)

    # Step 2: Compute depth of ponding
    depth = filled_dem - dem
    depth = np.where(depth > 0.1, depth, 0)  # Ignore < 10cm depth

    if flood_mask is not None:
        # Focus on areas near the flood extent
        from scipy.ndimage import binary_dilation
        expanded_flood = binary_dilation(flood_mask, iterations=50)
        if expanded_flood.shape == depth.shape:
            depth = depth * expanded_flood

    # Step 3: Label connected ponding regions
    ponding_mask = depth > 0.1
    labeled, n_regions = ndimage.label(ponding_mask)

    logger.info("Found %d potential ponding regions", n_regions)

    zones = []
    for region_id in range(1, n_regions + 1):
        region_mask = labeled == region_id
        region_depths = depth[region_mask]

        # Calculate volume
        volume_m3 = float(np.sum(region_depths) * pixel_area)

        if volume_m3 < volume_threshold_m3:
            continue

        area_m2 = float(region_mask.sum() * pixel_area)
        max_depth = float(np.max(region_depths))
        avg_depth = float(np.mean(region_depths))

        # Get centroid and dam elevation
        rows, cols = np.where(region_mask)
        center_row = int(np.mean(rows))
        center_col = int(np.mean(cols))
        center_x, center_y = rasterio.transform.xy(transform, center_row, center_col)

        # Dam elevation = maximum elevation at the ponding boundary
        boundary = ndimage.binary_dilation(region_mask) & ~region_mask
        if boundary.any():
            dam_elevation = float(np.max(dem[boundary]))
        else:
            dam_elevation = float(np.max(dem[region_mask]))

        # Risk assessment
        risk_level = _assess_ponding_risk(volume_m3, max_depth, area_m2)

        zone = {
            "id": str(uuid.uuid4()),
            "centroid_x": center_x,
            "centroid_y": center_y,
            "area_m2": round(area_m2, 1),
            "volume_m3": round(volume_m3, 1),
            "max_depth_m": round(max_depth, 2),
            "avg_depth_m": round(avg_depth, 2),
            "dam_elevation_m": round(dam_elevation, 1),
            "risk_level": risk_level,
        }
        zones.append(zone)

    zones.sort(key=lambda z: z["volume_m3"], reverse=True)

    logger.info(
        "Ponding detection: %d significant zones (>%.0f m³)",
        len(zones), volume_threshold_m3,
    )

    return zones


def _fill_depressions(dem: np.ndarray, max_iterations: int = 100) -> np.ndarray:
    """
    Fill DEM depressions using an iterative morphological approach.

    Each iteration raises pit pixels to the minimum of their neighbors.
    Converges when no more changes occur.
    """
    filled = dem.copy()
    filled = np.where(np.isfinite(filled), filled, np.nanmax(filled))

    for i in range(max_iterations):
        # Maximum filter (morphological dilation with minimum)
        neighbor_min = ndimage.minimum_filter(filled, size=3)
        raised = np.maximum(filled, neighbor_min)

        # Don't raise pixels above their original elevation
        raised = np.minimum(raised, np.nanmax(dem) + 1)

        # Check convergence
        changed = np.sum(raised != filled)
        filled = raised

        if changed == 0:
            logger.debug("  Depression filling converged at iteration %d", i + 1)
            break

    return filled


def _assess_ponding_risk(volume_m3: float, max_depth_m: float, area_m2: float) -> str:
    """Assign risk level based on ponding characteristics."""
    if volume_m3 > 5_000_000 or max_depth_m > 20:
        return "critical"
    elif volume_m3 > 1_000_000 or max_depth_m > 10:
        return "high"
    elif volume_m3 > 500_000 or max_depth_m > 5:
        return "medium"
    else:
        return "low"


# ─── D8 Flow-Path Tracer ────────────────────────────────────

def trace_d8_flow_path(
    dem_path: Path,
    origin_x: float,
    origin_y: float,
    max_steps: int = 10000,
) -> dict[str, Any]:
    """
    Trace a D8 (steepest-descent) flow path from a point downstream.

    The D8 algorithm routes flow from each cell to the one of its
    8 neighbors with the steepest downhill gradient.

    Used to trace the likely path of a glacial lake outburst flood (GLOF)
    or avalanche debris flow from the collapse origin downstream.

    Args:
        dem_path: Path to UTM-projected DEM GeoTIFF.
        origin_x: X coordinate of collapse origin (in DEM CRS).
        origin_y: Y coordinate of collapse origin (in DEM CRS).
        max_steps: Maximum number of cells to trace.

    Returns:
        Dict with path coordinates, total length, elevation drop, etc.
    """
    logger.info("Tracing D8 flow path from (%.1f, %.1f)...", origin_x, origin_y)

    with rasterio.open(dem_path) as ds:
        dem = ds.read(1).astype(np.float32)
        transform = ds.transform
        pixel_size = abs(transform.a)

    # Convert origin to pixel coordinates
    col, row = ~transform * (origin_x, origin_y)
    row, col = int(row), int(col)

    if not (0 <= row < dem.shape[0] and 0 <= col < dem.shape[1]):
        logger.warning("Origin point outside DEM extent")
        return {"path": [], "total_length_m": 0, "total_drop_m": 0}

    # D8 neighbor offsets: [dy, dx] for 8 directions
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]
    # Diagonal distance = pixel_size * √2
    distances = [
        pixel_size * 1.414, pixel_size, pixel_size * 1.414,
        pixel_size,                      pixel_size,
        pixel_size * 1.414, pixel_size, pixel_size * 1.414,
    ]

    path_coords = []
    visited = set()
    current_row, current_col = row, col

    origin_elevation = float(dem[row, col])
    total_length = 0.0

    for step in range(max_steps):
        # Record current position
        x, y = rasterio.transform.xy(transform, current_row, current_col)
        path_coords.append((x, y))
        visited.add((current_row, current_col))

        current_elevation = dem[current_row, current_col]

        # Find steepest downhill neighbor
        best_slope = 0.0
        best_dir = None

        for i, (dy, dx) in enumerate(neighbors):
            nr, nc = current_row + dy, current_col + dx

            # Bounds check
            if not (0 <= nr < dem.shape[0] and 0 <= nc < dem.shape[1]):
                continue

            if (nr, nc) in visited:
                continue

            neighbor_elevation = dem[nr, nc]
            if not np.isfinite(neighbor_elevation):
                continue

            # Slope = (current - neighbor) / distance
            slope = (current_elevation - neighbor_elevation) / distances[i]

            if slope > best_slope:
                best_slope = slope
                best_dir = i

        if best_dir is None:
            # Reached a sink or flat area
            logger.info("Flow path reached sink at step %d", step)
            break

        # Move to steepest neighbor
        dy, dx = neighbors[best_dir]
        total_length += distances[best_dir]
        current_row += dy
        current_col += dx

    end_elevation = float(dem[current_row, current_col])
    total_drop = origin_elevation - end_elevation

    result = {
        "path": path_coords,
        "total_length_m": round(total_length, 1),
        "total_drop_m": round(total_drop, 1),
        "origin_elevation_m": round(origin_elevation, 1),
        "end_elevation_m": round(end_elevation, 1),
        "n_steps": len(path_coords),
        "avg_slope_deg": round(
            np.degrees(np.arctan(total_drop / max(total_length, 1))), 2
        ),
    }

    logger.info(
        "Flow path: %d steps, %.1f km, %.0f m drop, avg slope=%.1f°",
        result["n_steps"], result["total_length_m"] / 1000,
        result["total_drop_m"], result["avg_slope_deg"],
    )

    return result
