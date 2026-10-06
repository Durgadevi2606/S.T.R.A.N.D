"""
S.T.R.A.N.D — Tests: Ensemble Voter, Morphology & Vectorization
"""

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds


class TestEnsembleVote:
    """Test the 3-method majority voting system."""

    def test_unanimous_agreement(self):
        from strand.segmentation.ensemble import ensemble_vote
        mask = np.ones((50, 50), dtype=bool)
        prob = np.ones((50, 50), dtype=np.float32)
        flood, conf = ensemble_vote(mask, mask, prob)
        assert flood.all(), "All methods agree → all pixels should be flood"
        assert conf.min() == 1.0, "Unanimous agreement → confidence should be 1.0"

    def test_unanimous_no_flood(self):
        from strand.segmentation.ensemble import ensemble_vote
        mask = np.zeros((50, 50), dtype=bool)
        prob = np.zeros((50, 50), dtype=np.float32)
        flood, conf = ensemble_vote(mask, mask, prob)
        assert not flood.any(), "No methods agree → no flood"
        assert conf.max() == 0.0

    def test_majority_vote_2_of_3(self):
        from strand.segmentation.ensemble import ensemble_vote
        vv_mask = np.ones((50, 50), dtype=bool)
        vh_mask = np.ones((50, 50), dtype=bool)
        prob = np.zeros((50, 50), dtype=np.float32)  # U-Net disagrees
        flood, conf = ensemble_vote(vv_mask, vh_mask, prob, min_agreement=2)
        assert flood.all(), "2 of 3 agree → should be flood (min_agreement=2)"

    def test_single_method_insufficient(self):
        from strand.segmentation.ensemble import ensemble_vote
        vv_mask = np.ones((50, 50), dtype=bool)
        vh_mask = np.zeros((50, 50), dtype=bool)
        prob = np.zeros((50, 50), dtype=np.float32)
        flood, conf = ensemble_vote(vv_mask, vh_mask, prob, min_agreement=2)
        assert not flood.any(), "Only 1 method → insufficient for min_agreement=2"

    def test_confidence_levels(self):
        from strand.segmentation.ensemble import ensemble_vote
        vv = np.array([[True, True, False]], dtype=bool)
        vh = np.array([[True, False, False]], dtype=bool)
        prob = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        flood, conf = ensemble_vote(vv, vh, prob, min_agreement=1)
        assert conf[0, 0] == pytest.approx(1.0)
        assert conf[0, 1] == pytest.approx(1 / 3, abs=0.01)


class TestMorphologicalCleanup:
    """Test morphological post-processing."""

    def test_removes_small_objects(self):
        from strand.segmentation.ensemble import morphological_cleanup
        mask = np.zeros((100, 100), dtype=bool)
        # Small noise (< min_component_pixels)
        mask[5, 5] = True
        mask[6, 5] = True
        cleaned = morphological_cleanup(mask, min_component_pixels=50)
        assert cleaned.sum() == 0, "Small objects should be removed"

    def test_preserves_large_objects(self):
        from strand.segmentation.ensemble import morphological_cleanup
        mask = np.zeros((100, 100), dtype=bool)
        mask[20:40, 20:40] = True  # 400 pixels
        cleaned = morphological_cleanup(mask, min_component_pixels=50)
        assert cleaned.sum() > 0, "Large objects should be preserved"

    def test_fills_small_holes(self):
        from strand.segmentation.ensemble import morphological_cleanup
        mask = np.zeros((100, 100), dtype=bool)
        mask[20:50, 20:50] = True
        mask[30:35, 30:35] = False  # Small hole (25 pixels)
        cleaned = morphological_cleanup(mask, min_component_pixels=10, fill_holes_max_pixels=50)
        # The hole should be filled
        assert cleaned[32, 32], "Small holes should be filled"


class TestVectorization:
    """Test raster-to-vector polygon conversion."""

    def test_creates_polygons(self, flood_mask, small_transform):
        from strand.segmentation.ensemble import vectorize_flood_mask
        features = vectorize_flood_mask(
            flood_mask, small_transform, CRS.from_epsg(32645),
            simplify_tolerance=0,
        )
        assert len(features) > 0, "Should produce at least one polygon"
        assert features[0]["type"] == "Feature"
        assert features[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_area_property(self, flood_mask, small_transform):
        from strand.segmentation.ensemble import vectorize_flood_mask
        features = vectorize_flood_mask(
            flood_mask, small_transform, CRS.from_epsg(32645),
        )
        for feat in features:
            assert "area_m2" in feat["properties"]
            assert feat["properties"]["area_m2"] > 0

    def test_empty_mask(self, small_transform):
        from strand.segmentation.ensemble import vectorize_flood_mask
        empty = np.zeros((100, 100), dtype=bool)
        features = vectorize_flood_mask(
            empty, small_transform, CRS.from_epsg(32645),
        )
        assert len(features) == 0

    def test_sorted_by_area(self, small_transform):
        from strand.segmentation.ensemble import vectorize_flood_mask
        mask = np.zeros((100, 100), dtype=bool)
        mask[10:50, 10:50] = True  # Large
        mask[70:75, 70:75] = True  # Small
        features = vectorize_flood_mask(
            mask, small_transform, CRS.from_epsg(32645),
        )
        if len(features) >= 2:
            assert features[0]["properties"]["area_m2"] >= features[1]["properties"]["area_m2"]
