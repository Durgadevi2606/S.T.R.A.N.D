"""
S.T.R.A.N.D — Tests: Infrastructure Overlay (Road/Bridge/Building Damage)
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

from tests.conftest import AOI_WEST_UTM, AOI_SOUTH_UTM, UTM_CRS


class TestRoadDamage:
    """Test road segment classification by flood intersection."""

    def test_intact_road(self, roads_gdf):
        from strand.overlay.road_damage import classify_road_damage
        # Empty flood → all roads intact
        flood = gpd.GeoDataFrame(columns=["geometry"], crs=UTM_CRS)
        result = classify_road_damage(roads_gdf, flood)
        assert all(result["damage_class"] == "intact")
        assert all(result["flood_intersection_ratio"] == 0.0)

    def test_severed_road(self):
        from strand.overlay.road_damage import classify_road_damage
        # Road entirely inside flood polygon
        road = gpd.GeoDataFrame(
            [{"id": "r1", "geometry": LineString([(0, 0), (100, 0)])}],
            crs=UTM_CRS,
        )
        road["length_m"] = road.geometry.length
        flood = gpd.GeoDataFrame(
            [{"id": "f1", "geometry": box(-10, -10, 110, 10)}],
            crs=UTM_CRS,
        )
        result = classify_road_damage(road, flood)
        assert result.iloc[0]["damage_class"] == "severed"
        assert result.iloc[0]["flood_intersection_ratio"] > 0.9

    def test_partial_flood(self):
        from strand.overlay.road_damage import classify_road_damage
        # Road partially inside flood (30%)
        road = gpd.GeoDataFrame(
            [{"id": "r1", "geometry": LineString([(0, 0), (100, 0)])}],
            crs=UTM_CRS,
        )
        road["length_m"] = road.geometry.length
        flood = gpd.GeoDataFrame(
            [{"id": "f1", "geometry": box(-5, -5, 30, 5)}],  # 30% of road
            crs=UTM_CRS,
        )
        result = classify_road_damage(road, flood)
        assert result.iloc[0]["damage_class"] == "partially_flooded"

    def test_empty_roads(self, flood_gdf):
        from strand.overlay.road_damage import classify_road_damage
        empty_roads = gpd.GeoDataFrame(columns=["geometry", "length_m"], crs=UTM_CRS)
        result = classify_road_damage(empty_roads, flood_gdf)
        assert result.empty


class TestBridgeDamage:
    """Test bridge classification by buffer flood overlap."""

    def test_intact_bridge(self, bridges_gdf):
        from strand.overlay.bridge_damage import classify_bridge_damage
        flood = gpd.GeoDataFrame(columns=["geometry"], crs=UTM_CRS)
        result = classify_bridge_damage(bridges_gdf, flood)
        assert all(result["damage_class"] == "intact")

    def test_destroyed_bridge(self):
        from strand.overlay.bridge_damage import classify_bridge_damage
        bridge = gpd.GeoDataFrame(
            [{"id": "b1", "geometry": Point(50, 50)}],
            crs=UTM_CRS,
        )
        # Flood covers the entire buffer zone
        flood = gpd.GeoDataFrame(
            [{"id": "f1", "geometry": box(-100, -100, 200, 200)}],
            crs=UTM_CRS,
        )
        result = classify_bridge_damage(bridge, flood, buffer_radius_m=50)
        assert result.iloc[0]["damage_class"] == "destroyed"
        assert result.iloc[0]["buffer_flood_ratio"] > 0.9

    def test_buffer_radius_matters(self):
        from strand.overlay.bridge_damage import classify_bridge_damage
        bridge = gpd.GeoDataFrame(
            [{"id": "b1", "geometry": Point(50, 50)}],
            crs=UTM_CRS,
        )
        flood = gpd.GeoDataFrame(
            [{"id": "f1", "geometry": box(90, 40, 200, 60)}],  # ~40m away
            crs=UTM_CRS,
        )
        # Small buffer → intact; large buffer → damaged
        result_small = classify_bridge_damage(bridge, flood, buffer_radius_m=30)
        result_large = classify_bridge_damage(bridge, flood, buffer_radius_m=100)
        assert result_small.iloc[0]["damage_class"] == "intact"
        assert result_large.iloc[0]["damage_class"] != "intact"


class TestBuildingDamage:
    """Test building footprint classification."""

    def test_safe_buildings(self, buildings_gdf):
        from strand.overlay.building_damage import classify_building_damage
        flood = gpd.GeoDataFrame(columns=["geometry"], crs=UTM_CRS)
        result = classify_building_damage(buildings_gdf, flood)
        assert all(result["damage_class"] == "safe")

    def test_submerged_building(self):
        from strand.overlay.building_damage import classify_building_damage
        bldg = gpd.GeoDataFrame(
            [{"id": "b1", "geometry": box(0, 0, 20, 20)}],
            crs=UTM_CRS,
        )
        flood = gpd.GeoDataFrame(
            [{"id": "f1", "geometry": box(-10, -10, 30, 30)}],
            crs=UTM_CRS,
        )
        result = classify_building_damage(bldg, flood)
        assert result.iloc[0]["damage_class"] == "submerged"

    def test_population_estimate(self):
        from strand.overlay.building_damage import estimate_affected_population
        bldg = gpd.GeoDataFrame(
            [
                {"damage_class": "submerged"},
                {"damage_class": "flood_contact"},
                {"damage_class": "safe"},
            ]
        )
        result = estimate_affected_population(bldg, avg_household_size=4.5)
        assert result["affected_buildings"] == 2
        assert result["affected_population"] == 9  # 2 × 4.5
        assert result["submerged_buildings"] == 1
