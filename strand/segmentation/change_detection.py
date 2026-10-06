"""
S.T.R.A.N.D — SAR Change Detection Engine

Computes log-ratio difference images between pre- and post-flood SAR pairs
and applies adaptive thresholding to produce initial flood binary masks.

Key methods:
- Log-ratio: log₁₀(σ⁰_post / σ⁰_pre) for both VV and VH polarizations
- Otsu adaptive thresholding on the log-ratio images
- Kittler-Illingworth minimum error thresholding as alternative
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio

from strand.config import SLOPE_FALSE_POSITIVE_THRESHOLD_DEG

logger = logging.getLogger(__name__)

# Small epsilon to avoid log(0) and division by zero
EPSILON = 1e-10


def compute_log_ratio(
    pre_array: np.ndarray, post_array: np.ndarray
) -> np.ndarray:
    """
    Compute the log-ratio change detection image.

    Formula: R = log₁₀(σ⁰_post / σ⁰_pre)

    - Negative values → backscatter decrease → likely water (specular reflection)
    - Positive values → backscatter increase → likely debris/roughness
    - Near zero → no change

    Args:
        pre_array: Pre-event calibrated σ⁰ (linear power, float32).
        post_array: Post-event calibrated σ⁰ (linear power, float32).

    Returns:
        Log-ratio array (float32). NaN where inputs are invalid.
    """
    # Ensure float and replace invalid values
    pre = np.where(pre_array > EPSILON, pre_array, EPSILON).astype(np.float32)
    post = np.where(post_array > EPSILON, post_array, EPSILON).astype(np.float32)

    ratio = post / pre
    log_ratio = np.log10(ratio)

    # Mask out extreme outliers (likely calibration artifacts)
    log_ratio = np.where(np.abs(log_ratio) < 5.0, log_ratio, np.nan)

    valid_pct = np.count_nonzero(~np.isnan(log_ratio)) / log_ratio.size * 100
    logger.info(
        "Log-ratio: range=[%.3f, %.3f], mean=%.4f, valid=%.1f%%",
        np.nanmin(log_ratio), np.nanmax(log_ratio),
        np.nanmean(log_ratio), valid_pct,
    )

    return log_ratio


def compute_log_ratio_from_files(
    pre_path: Path, post_path: Path, output_path: Path
) -> Path:
    """
    Compute log-ratio from GeoTIFF files and write result.

    Args:
        pre_path: Path to pre-event σ⁰ GeoTIFF.
        post_path: Path to post-event σ⁰ GeoTIFF.
        output_path: Path for output log-ratio GeoTIFF.

    Returns:
        Path to the log-ratio GeoTIFF.
    """
    with rasterio.open(pre_path) as pre_ds:
        pre_data = pre_ds.read(1).astype(np.float32)
        profile = pre_ds.profile.copy()

    with rasterio.open(post_path) as post_ds:
        post_data = post_ds.read(1).astype(np.float32)

    log_ratio = compute_log_ratio(pre_data, post_data)

    profile.update(dtype="float32", compress="deflate", predictor=2)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(log_ratio, 1)

    logger.info("Log-ratio written to %s", output_path)
    return output_path


def otsu_threshold(image: np.ndarray, invert: bool = True) -> np.ndarray:
    """
    Apply Otsu's adaptive thresholding to a log-ratio image.

    For flood detection on VV, we look for NEGATIVE log-ratio values
    (backscatter decrease due to specular water reflection).

    Args:
        image: Log-ratio image (float32).
        invert: If True, threshold on negative values (water detection).
                If False, threshold on positive values (debris detection).

    Returns:
        Binary mask (bool): True = detected change, False = no change.
    """
    from skimage.filters import threshold_otsu

    # Clean NaN values for thresholding
    clean = image[np.isfinite(image)]

    if len(clean) == 0:
        logger.warning("No valid pixels for Otsu thresholding")
        return np.zeros(image.shape, dtype=bool)

    if invert:
        # For water detection: look at the negative tail
        # Invert so Otsu finds the "bright" (most negative) pixels
        inverted = -clean
        thresh = -threshold_otsu(inverted)
        mask = image < thresh
    else:
        # For debris detection: look at the positive tail
        thresh = threshold_otsu(clean)
        mask = image > thresh

    # Handle NaN pixels
    mask = np.where(np.isfinite(image), mask, False)

    detected_pct = mask.sum() / mask.size * 100
    logger.info(
        "Otsu threshold: %.4f, detected=%.1f%% of pixels",
        thresh, detected_pct,
    )

    return mask


def kittler_illingworth_threshold(image: np.ndarray) -> float:
    """
    Kittler-Illingworth minimum error thresholding.

    An alternative to Otsu that assumes the histogram consists of
    two Gaussian distributions. Often performs better on SAR data
    which has multiplicative (Rayleigh) noise characteristics.

    Args:
        image: Log-ratio image (float32).

    Returns:
        Optimal threshold value.
    """
    clean = image[np.isfinite(image)]
    if len(clean) == 0:
        return 0.0

    # Compute histogram
    n_bins = 256
    hist, bin_edges = np.histogram(clean, bins=n_bins)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    hist = hist.astype(np.float64)
    total = hist.sum()

    if total == 0:
        return 0.0

    best_threshold = bin_centers[0]
    min_error = float("inf")

    for i in range(1, n_bins - 1):
        # Class probabilities
        w0 = hist[:i].sum() / total
        w1 = hist[i:].sum() / total

        if w0 < 1e-10 or w1 < 1e-10:
            continue

        # Class means
        mu0 = np.sum(bin_centers[:i] * hist[:i]) / (w0 * total)
        mu1 = np.sum(bin_centers[i:] * hist[i:]) / (w1 * total)

        # Class variances
        var0 = np.sum((bin_centers[:i] - mu0) ** 2 * hist[:i]) / (w0 * total)
        var1 = np.sum((bin_centers[i:] - mu1) ** 2 * hist[i:]) / (w1 * total)

        if var0 < 1e-10 or var1 < 1e-10:
            continue

        # Kittler-Illingworth criterion
        error = (
            w0 * np.log(np.sqrt(var0) / w0)
            + w1 * np.log(np.sqrt(var1) / w1)
        )

        if error < min_error:
            min_error = error
            best_threshold = bin_centers[i]

    logger.info("Kittler-Illingworth threshold: %.4f", best_threshold)
    return best_threshold


def apply_slope_mask(
    flood_mask: np.ndarray,
    dem_path: Path,
    max_slope_deg: float = SLOPE_FALSE_POSITIVE_THRESHOLD_DEG,
) -> np.ndarray:
    """
    Remove flood false positives on steep slopes.

    Radar shadow and layover in mountain terrain can mimic flood
    signatures (low backscatter in shadow zones). We remove flood
    detections where the DEM slope exceeds a threshold.

    Args:
        flood_mask: Binary flood mask (True = flood).
        dem_path: Path to DEM GeoTIFF (same CRS/resolution as mask).
        max_slope_deg: Maximum slope to keep flood detections.

    Returns:
        Corrected flood mask with steep-slope false positives removed.
    """
    try:
        with rasterio.open(dem_path) as ds:
            dem = ds.read(1).astype(np.float32)
            pixel_size = abs(ds.transform.a)

        # Compute slope
        dy, dx = np.gradient(dem, pixel_size)
        slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

        # Resize if needed
        if slope_deg.shape != flood_mask.shape:
            from scipy.ndimage import zoom
            factors = (
                flood_mask.shape[0] / slope_deg.shape[0],
                flood_mask.shape[1] / slope_deg.shape[1],
            )
            slope_deg = zoom(slope_deg, factors, order=1)

        # Remove flood detections on steep slopes
        steep_mask = slope_deg > max_slope_deg
        removed = np.sum(flood_mask & steep_mask)
        corrected = flood_mask & ~steep_mask

        logger.info(
            "Slope masking: removed %d false positive pixels (slope > %.0f°)",
            removed, max_slope_deg,
        )

        return corrected

    except Exception as e:
        logger.warning("Slope masking failed: %s. Returning original mask.", e)
        return flood_mask
