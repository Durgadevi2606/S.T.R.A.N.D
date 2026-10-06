"""
S.T.R.A.N.D — Ensemble Voter, Morphological Cleanup & Vectorizer

Combines threshold and U-Net predictions via majority voting,
applies morphological cleanup, and vectorizes the flood mask
to GeoJSON polygons.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from strand.config import MIN_FLOOD_COMPONENT_PIXELS

logger = logging.getLogger(__name__)


# ─── Ensemble Voter ──────────────────────────────────────────

def ensemble_vote(
    threshold_mask_vv: np.ndarray,
    threshold_mask_vh: np.ndarray,
    unet_prob: np.ndarray,
    unet_threshold: float = 0.5,
    min_agreement: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Combine multiple flood detection methods via majority voting.

    Methods:
    1. Otsu threshold on VV log-ratio
    2. Otsu threshold on VH log-ratio
    3. U-Net probability > unet_threshold

    A pixel is classified as flood if at least `min_agreement` methods agree.

    Args:
        threshold_mask_vv: Binary mask from VV thresholding.
        threshold_mask_vh: Binary mask from VH thresholding.
        unet_prob: U-Net flood probability map (0–1).
        unet_threshold: Probability threshold for U-Net binary conversion.
        min_agreement: Minimum number of methods that must agree (1–3).

    Returns:
        Tuple of:
        - flood_mask: Final binary flood mask (bool).
        - confidence: Per-pixel confidence score (0.0, 0.33, 0.67, 1.0).
    """
    unet_mask = unet_prob >= unet_threshold

    # Count agreements
    agreement = (
        threshold_mask_vv.astype(np.int8)
        + threshold_mask_vh.astype(np.int8)
        + unet_mask.astype(np.int8)
    )

    # Majority vote
    flood_mask = agreement >= min_agreement

    # Confidence score based on agreement level
    confidence = agreement.astype(np.float32) / 3.0

    # Statistics
    total = flood_mask.size
    flood_pct = flood_mask.sum() / total * 100
    logger.info(
        "Ensemble vote: %d/%d pixels (%.1f%%) classified as flood (min_agreement=%d)",
        flood_mask.sum(), total, flood_pct, min_agreement,
    )
    logger.info(
        "  Agreement distribution: 0=%d, 1=%d, 2=%d, 3=%d",
        (agreement == 0).sum(),
        (agreement == 1).sum(),
        (agreement == 2).sum(),
        (agreement == 3).sum(),
    )

    return flood_mask, confidence


# ─── Morphological Cleanup ───────────────────────────────────

def morphological_cleanup(
    mask: np.ndarray,
    min_component_pixels: int = MIN_FLOOD_COMPONENT_PIXELS,
    opening_kernel_size: int = 3,
    closing_kernel_size: int = 5,
    fill_holes_max_pixels: int = 100,
) -> np.ndarray:
    """
    Clean up the binary flood mask using morphological operations.

    Pipeline:
    1. Binary opening (remove small noise spots)
    2. Binary closing (fill small gaps in flood regions)
    3. Remove connected components smaller than threshold
    4. Fill small holes inside flood regions

    Args:
        mask: Binary flood mask (bool array).
        min_component_pixels: Minimum size of flood regions to keep.
        opening_kernel_size: Kernel size for morphological opening.
        closing_kernel_size: Kernel size for morphological closing.
        fill_holes_max_pixels: Maximum hole size to fill.

    Returns:
        Cleaned binary flood mask.
    """
    from scipy import ndimage
    from skimage.morphology import (
        binary_closing,
        binary_opening,
        disk,
        remove_small_holes,
        remove_small_objects,
    )

    original_count = mask.sum()

    # Step 1: Opening (erode then dilate) — removes small noise
    cleaned = binary_opening(mask, disk(opening_kernel_size // 2))
    logger.info("  After opening: %d → %d pixels", original_count, cleaned.sum())

    # Step 2: Closing (dilate then erode) — fills small gaps
    cleaned = binary_closing(cleaned, disk(closing_kernel_size // 2))
    logger.info("  After closing: %d pixels", cleaned.sum())

    # Step 3: Remove small connected components
    cleaned = remove_small_objects(cleaned, min_size=min_component_pixels)
    logger.info("  After small object removal (<%d px): %d pixels",
                min_component_pixels, cleaned.sum())

    # Step 4: Fill small holes
    cleaned = remove_small_holes(cleaned, area_threshold=fill_holes_max_pixels)
    logger.info("  After hole filling (<%d px): %d pixels",
                fill_holes_max_pixels, cleaned.sum())

    logger.info(
        "Morphological cleanup: %d → %d flood pixels (%.1f%% retained)",
        original_count, cleaned.sum(),
        cleaned.sum() / max(original_count, 1) * 100,
    )

    return cleaned.astype(bool)


# ─── Vectorization ───────────────────────────────────────────

def vectorize_flood_mask(
    mask: np.ndarray,
    transform: rasterio.transform.Affine,
    crs: rasterio.crs.CRS,
    simplify_tolerance: float = 5.0,
) -> list[dict]:
    """
    Convert a binary flood mask raster to GeoJSON polygon features.

    Uses rasterio.features.shapes for efficient polygonization,
    then applies Douglas-Peucker simplification to reduce vertex count.

    Args:
        mask: Binary flood mask (bool array).
        transform: Affine transform of the raster.
        crs: Coordinate reference system.
        simplify_tolerance: Simplification tolerance in CRS units (meters for UTM).

    Returns:
        List of GeoJSON Feature dicts with properties:
        - id: Unique polygon ID
        - area_m2: Polygon area in square meters
        - confidence: Average confidence in polygon (if available)
    """
    logger.info("Vectorizing flood mask (%d flood pixels)...", mask.sum())

    # Convert to uint8 for rasterio.features.shapes
    mask_uint8 = mask.astype(np.uint8)

    features = []

    for geom_dict, value in rasterio_shapes(mask_uint8, transform=transform):
        if value == 0:
            continue  # Skip non-flood polygons

        geom = shape(geom_dict)

        # Simplify geometry
        if simplify_tolerance > 0:
            geom = geom.simplify(simplify_tolerance, preserve_topology=True)

        # Skip tiny fragments
        if geom.is_empty or geom.area < 100:  # < 100 m²
            continue

        feature = {
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "id": str(uuid.uuid4()),
                "area_m2": round(geom.area, 1),
            },
        }
        features.append(feature)

    # Sort by area (largest first)
    features.sort(key=lambda f: f["properties"]["area_m2"], reverse=True)

    total_area = sum(f["properties"]["area_m2"] for f in features)
    logger.info(
        "Vectorization complete: %d polygons, total area=%.2f km²",
        len(features), total_area / 1e6,
    )

    return features


def save_flood_mask_geotiff(
    mask: np.ndarray,
    confidence: np.ndarray,
    reference_path: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """
    Save the flood mask and confidence raster as GeoTIFFs.

    Uses the CRS and transform from a reference file (the preprocessed SAR).

    Args:
        mask: Binary flood mask (bool).
        confidence: Per-pixel confidence (0–1).
        reference_path: Path to reference GeoTIFF for CRS/transform.
        output_dir: Output directory.

    Returns:
        Tuple of (mask_path, confidence_path).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(reference_path) as ref:
        profile = ref.profile.copy()

    # Save binary mask
    mask_path = output_dir / "flood_mask.tif"
    profile.update(dtype="uint8", count=1, compress="deflate")
    with rasterio.open(mask_path, "w", **profile) as dst:
        dst.write(mask.astype(np.uint8), 1)

    # Save confidence
    conf_path = output_dir / "flood_confidence.tif"
    profile.update(dtype="float32")
    with rasterio.open(conf_path, "w", **profile) as dst:
        dst.write(confidence, 1)

    logger.info("Saved flood mask to %s", mask_path)
    logger.info("Saved confidence to %s", conf_path)

    return mask_path, conf_path


def save_flood_geojson(
    features: list[dict],
    output_path: Path,
    crs_epsg: int = 4326,
) -> Path:
    """Save flood polygon features as a GeoJSON file."""
    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": f"urn:ogc:def:crs:EPSG::{crs_epsg}"},
        },
        "features": features,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=2)

    logger.info("Saved %d flood polygons to %s", len(features), output_path)
    return output_path
