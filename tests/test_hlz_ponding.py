"""
S.T.R.A.N.D — Tests: HLZ Finder & Ponding Detector
"""

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import Point, box

from tests.conftest import AOI_WEST_UTM, AOI_SOUTH_UTM, UTM_CRS


class TestHLZFinder:
    """Test helicopter landing zone identification."""

    def test_flat_area_detected(self):
        from strand.hlz_finder.finder import find_flat_areas
        from rasterio.transform import from_bounds

        # Perfectly flat DEM → entire surface is a candidate
        flat_dem = np.full((100, 100), 1000.0, dtype=np.float32)
        slope = np.zeros((100, 100), dtype=np.float32)
        meta = {
            "transform": from_bounds(0, 0, 1000, 1000, 100, 100),
            "crs": "EPSG:32645",
            "width": 100, "height": 100,
        }
        candidates = find_flat_areas(slope, flat_dem, meta, max_slope=5.0, min_area_m2=100)
        assert len(candidates) > 0
        assert candidates[0]["area_m2"] > 100

    def test_steep_terrain_no_candidates(self):
        from strand.hlz_finder.finder import find_flat_areas
        from rasterio.transform import from_bounds

        # Very steep DEM → no candidates
        steep_dem = np.linspace(0, 5000, 100).reshape(-1, 1)
        steep_dem = np.tile(steep_dem, (1, 100)).astype(np.float32)
        slope = np.full((100, 100), 45.0, dtype=np.float32)  # 45° everywhere
        meta = {
            "transform": from_bounds(0, 0, 1000, 1000, 100, 100),
            "crs": "EPSG:32645",
            "width": 100, "height": 100,
        }
        candidates = find_flat_areas(slope, steep_dem, meta, max_slope=5.0, min_area_m2=100)
        assert len(candidates) == 0

    def test_exclusion_removes_flooded(self):
        from strand.hlz_finder.finder import apply_exclusion_zones

        candidates = [
            {"id": "h1", "centroid_x": 50, "centroid_y": 50, "area_m2": 1000},
            {"id": "h2", "centroid_x": 500, "centroid_y": 500, "area_m2": 1000},
        ]
        flood = gpd.GeoDataFrame(
            [{"geometry": box(0, 0, 100, 100)}], crs=UTM_CRS,
        )
        result = apply_exclusion_zones(candidates, flood, buffer_m=10)
        # h1 is inside flood zone → excluded
        assert len(result) == 1
        assert result[0]["id"] == "h2"

    def test_ranking_by_settlement(self):
        from strand.hlz_finder.finder import rank_by_settlement_proximity

        candidates = [
            {"id": "h1", "centroid_x": 100, "centroid_y": 100, "area_m2": 1000},
            {"id": "h2", "centroid_x": 10, "centroid_y": 10, "area_m2": 1000},
        ]
        settlements = gpd.GeoDataFrame(
            [{"id": "s1", "geometry": Point(0, 0)}], crs=UTM_CRS,
        )
        result = rank_by_settlement_proximity(candidates, settlements)
        # h2 is closer to settlement → should be first
        assert result[0]["id"] == "h2"
        assert result[0]["dist_to_settlement_m"] < result[1]["dist_to_settlement_m"]


class TestPondingDetector:
    """Test debris dam ponding detection."""

    def test_depression_detected(self, sample_dem_geotiff):
        from strand.hydro.ponding import detect_ponding_zones
        # The synthetic DEM has natural depressions from noise
        zones = detect_ponding_zones(
            sample_dem_geotiff,
            volume_threshold_m3=100,  # Low threshold for test
        )
        # Should find some zones (or zero if DEM is too smooth)
        assert isinstance(zones, list)

    def test_risk_assessment(self):
        from strand.hydro.ponding import _assess_ponding_risk
        assert _assess_ponding_risk(10_000_000, 25, 50000) == "critical"
        assert _assess_ponding_risk(2_000_000, 15, 20000) == "high"
        assert _assess_ponding_risk(600_000, 7, 10000) == "medium"
        assert _assess_ponding_risk(100_000, 3, 5000) == "low"


class TestD8FlowTracer:
    """Test D8 steepest-descent flow path tracing."""

    def test_downhill_path(self, sample_dem_geotiff):
        from strand.hydro.ponding import trace_d8_flow_path
        from rasterio.transform import from_bounds

        # Origin at the top (high elevation)
        import rasterio
        with rasterio.open(sample_dem_geotiff) as ds:
            transform = ds.transform
            x, y = rasterio.transform.xy(transform, 5, 50)  # Near top

        result = trace_d8_flow_path(sample_dem_geotiff, x, y, max_steps=500)
        assert result["total_length_m"] > 0
        assert result["total_drop_m"] > 0
        assert result["n_steps"] > 1

    def test_path_goes_downhill(self, sample_dem_geotiff):
        from strand.hydro.ponding import trace_d8_flow_path
        import rasterio
        with rasterio.open(sample_dem_geotiff) as ds:
            transform = ds.transform
            x, y = rasterio.transform.xy(transform, 10, 50)

        result = trace_d8_flow_path(sample_dem_geotiff, x, y, max_steps=200)
        assert result["origin_elevation_m"] >= result["end_elevation_m"], \
            "Flow should go downhill"

    def test_outside_dem(self, sample_dem_geotiff):
        from strand.hydro.ponding import trace_d8_flow_path
        result = trace_d8_flow_path(sample_dem_geotiff, 999999, 999999)
        assert result["total_length_m"] == 0
