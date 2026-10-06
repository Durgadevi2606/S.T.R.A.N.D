"""
S.T.R.A.N.D — Sentinel-2 Optical Cross-Validation

Computes MNDWI (Modified Normalized Difference Water Index) from Sentinel-2
imagery and compares against the SAR-derived flood mask for validation.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio

logger = logging.getLogger(__name__)


def compute_mndwi(green_path: Path, swir_path: Path, output_path: Path) -> Path:
    """
    Compute MNDWI from Sentinel-2 B03 (Green) and B11 (SWIR).

    MNDWI = (Green - SWIR) / (Green + SWIR)

    Values:
    - High positive (> 0.3): Open water
    - Near zero: Bare soil, vegetation
    - Negative: Built-up areas

    Args:
        green_path: Path to B03 (Green, 10m) GeoTIFF.
        swir_path: Path to B11 (SWIR, 20m) GeoTIFF — resampled to 10m.
        output_path: Path for output MNDWI GeoTIFF.

    Returns:
        Path to MNDWI raster.
    """
    with rasterio.open(green_path) as ds:
        green = ds.read(1).astype(np.float32)
        profile = ds.profile.copy()

    with rasterio.open(swir_path) as ds:
        swir = ds.read(1).astype(np.float32)

    # Handle resolution mismatch (B11 is 20m, B03 is 10m)
    if swir.shape != green.shape:
        from scipy.ndimage import zoom
        factors = (green.shape[0] / swir.shape[0], green.shape[1] / swir.shape[1])
        swir = zoom(swir, factors, order=1)

    # Compute MNDWI
    denominator = green + swir
    denominator = np.where(denominator == 0, 1e-10, denominator)
    mndwi = (green - swir) / denominator

    # Clip to valid range
    mndwi = np.clip(mndwi, -1.0, 1.0)

    # Save
    profile.update(dtype="float32", count=1, compress="deflate")
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(mndwi, 1)

    logger.info(
        "MNDWI computed: range=[%.3f, %.3f], water pixels (>0.3)=%.1f%%",
        np.nanmin(mndwi), np.nanmax(mndwi),
        (mndwi > 0.3).sum() / mndwi.size * 100,
    )

    return output_path


def validate_sar_with_mndwi(
    sar_flood_mask: np.ndarray,
    mndwi_array: np.ndarray,
    mndwi_threshold: float = 0.3,
) -> dict[str, float]:
    """
    Compare SAR flood mask against MNDWI-derived water mask.

    Returns agreement metrics between the two independent methods.

    Args:
        sar_flood_mask: Binary SAR-derived flood mask.
        mndwi_array: MNDWI raster values.
        mndwi_threshold: Threshold to classify water from MNDWI.

    Returns:
        Dict with agreement metrics:
        - agreement_pct: Percentage of pixels where both methods agree
        - sar_only_pct: SAR detects flood but MNDWI does not
        - mndwi_only_pct: MNDWI detects water but SAR does not
        - both_flood_pct: Both detect flood
    """
    # Handle shape mismatch
    if mndwi_array.shape != sar_flood_mask.shape:
        from scipy.ndimage import zoom
        factors = (
            sar_flood_mask.shape[0] / mndwi_array.shape[0],
            sar_flood_mask.shape[1] / mndwi_array.shape[1],
        )
        mndwi_array = zoom(mndwi_array, factors, order=1)

    mndwi_water = mndwi_array > mndwi_threshold
    valid = np.isfinite(mndwi_array)
    total_valid = valid.sum()

    if total_valid == 0:
        logger.warning("No valid MNDWI pixels for validation")
        return {"agreement_pct": 0, "sar_only_pct": 0,
                "mndwi_only_pct": 0, "both_flood_pct": 0}

    both_flood = (sar_flood_mask & mndwi_water & valid).sum()
    both_clear = (~sar_flood_mask & ~mndwi_water & valid).sum()
    sar_only = (sar_flood_mask & ~mndwi_water & valid).sum()
    mndwi_only = (~sar_flood_mask & mndwi_water & valid).sum()

    agreement = (both_flood + both_clear) / total_valid * 100

    results = {
        "agreement_pct": round(agreement, 1),
        "both_flood_pct": round(both_flood / total_valid * 100, 1),
        "sar_only_pct": round(sar_only / total_valid * 100, 1),
        "mndwi_only_pct": round(mndwi_only / total_valid * 100, 1),
    }

    logger.info(
        "SAR vs MNDWI validation: agreement=%.1f%%, both_flood=%.1f%%, "
        "SAR-only=%.1f%%, MNDWI-only=%.1f%%",
        results["agreement_pct"], results["both_flood_pct"],
        results["sar_only_pct"], results["mndwi_only_pct"],
    )

    return results
