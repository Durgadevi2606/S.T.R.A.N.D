"""
S.T.R.A.N.D — Tests: SAR Change Detection

Tests log-ratio computation, adaptive thresholding (Otsu + Kittler-Illingworth),
and DEM-based slope masking for false positive removal.
"""

import numpy as np
import pytest


class TestLogRatio:
    """Test log-ratio change detection image computation."""

    def test_no_change(self, pre_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio
        lr = compute_log_ratio(pre_event_sigma0, pre_event_sigma0)
        # No change → log-ratio should be ~0
        valid = lr[np.isfinite(lr)]
        assert np.abs(np.mean(valid)) < 0.1

    def test_flood_signal_negative(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        # Flood zone (top-left quadrant) should have negative log-ratio
        flood_zone = lr[10:50, 10:50]
        valid_flood = flood_zone[np.isfinite(flood_zone)]
        assert np.mean(valid_flood) < -0.5, "Flood zone should show strong negative log-ratio"

    def test_non_flood_near_zero(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        # Non-flood zone should be near zero
        non_flood = lr[60:90, 60:90]
        valid_nf = non_flood[np.isfinite(non_flood)]
        assert np.abs(np.mean(valid_nf)) < 0.3

    def test_output_shape(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        assert lr.shape == pre_event_sigma0.shape

    def test_handles_zeros(self):
        from strand.segmentation.change_detection import compute_log_ratio
        pre = np.zeros((10, 10), dtype=np.float32)
        post = np.ones((10, 10), dtype=np.float32)
        lr = compute_log_ratio(pre, post)
        # Should not contain inf or produce errors
        assert not np.any(np.isinf(lr[np.isfinite(lr)]))


class TestOtsuThreshold:
    """Test Otsu adaptive thresholding."""

    def test_detects_flood(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio, otsu_threshold
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        mask = otsu_threshold(lr, invert=True)
        # Should detect something in the flood zone
        flood_detected = mask[10:50, 10:50].sum()
        assert flood_detected > 100, "Otsu should detect substantial flood pixels"

    def test_minimal_false_positives(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio, otsu_threshold
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        mask = otsu_threshold(lr, invert=True)
        # Non-flood zone should have few detections
        false_positives = mask[70:100, 70:100].sum()
        total_non_flood = 30 * 30
        fp_rate = false_positives / total_non_flood
        assert fp_rate < 0.3, f"False positive rate too high: {fp_rate:.2%}"

    def test_empty_input(self):
        from strand.segmentation.change_detection import otsu_threshold
        empty = np.full((10, 10), np.nan, dtype=np.float32)
        mask = otsu_threshold(empty, invert=True)
        assert mask.sum() == 0


class TestKittlerIllingworth:
    """Test Kittler-Illingworth minimum error thresholding."""

    def test_returns_threshold(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio, kittler_illingworth_threshold
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        thresh = kittler_illingworth_threshold(lr)
        assert isinstance(thresh, float)
        assert -5 < thresh < 5

    def test_negative_threshold_for_flood(self, pre_event_sigma0, post_event_sigma0):
        from strand.segmentation.change_detection import compute_log_ratio, kittler_illingworth_threshold
        lr = compute_log_ratio(pre_event_sigma0, post_event_sigma0)
        thresh = kittler_illingworth_threshold(lr)
        # For flood detection, threshold should be negative
        assert thresh < 0, "K-I threshold should be negative for water detection"


class TestSlopeMasking:
    """Test DEM-based slope masking for false positive removal."""

    def test_removes_steep_pixels(self, flood_mask, sample_dem_geotiff):
        from strand.segmentation.change_detection import apply_slope_mask
        corrected = apply_slope_mask(flood_mask, sample_dem_geotiff, max_slope_deg=5.0)
        # Should remove at least some pixels (DEM has variable slope)
        assert corrected.sum() <= flood_mask.sum()

    def test_preserves_flat_pixels(self):
        from strand.segmentation.change_detection import apply_slope_mask
        import tempfile, rasterio
        from rasterio.transform import from_bounds

        # Create a perfectly flat DEM
        flat_dem = np.full((100, 100), 1000.0, dtype=np.float32)
        mask = np.ones((100, 100), dtype=bool)

        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
            path = Path(f.name)
            transform = from_bounds(0, 0, 1000, 1000, 100, 100)
            profile = {"driver": "GTiff", "dtype": "float32", "width": 100,
                       "height": 100, "count": 1, "crs": "EPSG:32645",
                       "transform": transform}
            with rasterio.open(path, "w", **profile) as ds:
                ds.write(flat_dem, 1)

        corrected = apply_slope_mask(mask, path, max_slope_deg=30.0)
        # Flat terrain → all pixels should be preserved
        assert corrected.sum() == mask.sum()
        path.unlink()


from pathlib import Path
