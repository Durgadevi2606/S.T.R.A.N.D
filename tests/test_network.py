"""
S.T.R.A.N.D — Tests: Network Graph, Reachability & Urgency

Tests graph construction from road segments, settlement snapping,
Dijkstra-based isolation classification, and urgency scoring.
"""

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from tests.conftest import AOI_WEST_UTM, AOI_SOUTH_UTM, UTM_CRS


class TestGraphBuilder:
    """Test road network graph construction."""

    def test_graph_from_roads(self, roads_gdf):
        from strand.network_graph.graph_builder import build_road_graph
        # Set all roads as intact
        roads = roads_gdf.copy()
        roads["damage_class"] = "intact"
        G = build_road_graph(roads)
        assert G.number_of_nodes() > 0
        assert G.number_of_edges() > 0

    def test_severed_roads_removed(self):
        from strand.network_graph.graph_builder import build_road_graph
        roads = gpd.GeoDataFrame([
            {"id": "r1", "damage_class": "intact", "length_m": 100,
             "geometry": LineString([(0, 0), (100, 0)])},
            {"id": "r2", "damage_class": "severed", "length_m": 100,
             "geometry": LineString([(200, 0), (300, 0)])},
        ], crs=UTM_CRS)
        G = build_road_graph(roads)
        # Only intact road should have edges
        assert G.number_of_edges() == 1

    def test_degraded_weight_penalty(self):
        from strand.network_graph.graph_builder import build_road_graph
        roads = gpd.GeoDataFrame([
            {"id": "r1", "damage_class": "intact", "length_m": 100,
             "geometry": LineString([(0, 0), (100, 0)])},
            {"id": "r2", "damage_class": "partially_flooded", "length_m": 100,
             "geometry": LineString([(200, 0), (300, 0)])},
        ], crs=UTM_CRS)
        G = build_road_graph(roads)
        # Degraded edge should have 5× weight
        for u, v, data in G.edges(data=True):
            if data["damage_class"] == "partially_flooded":
                assert data["weight"] == pytest.approx(500.0)  # 100 × 5

    def test_pre_disaster_graph_all_intact(self, roads_gdf):
        from strand.network_graph.graph_builder import build_pre_disaster_graph
        roads = roads_gdf.copy()
        roads["damage_class"] = "severed"
        G = build_pre_disaster_graph(roads)
        # Pre-disaster should treat all roads as intact
        assert G.number_of_edges() > 0
        for u, v, data in G.edges(data=True):
            assert data["damage_class"] == "intact"


class TestSnapping:
    """Test point-to-graph node snapping."""

    def test_snap_within_distance(self):
        from strand.network_graph.graph_builder import build_road_graph, snap_points_to_graph
        roads = gpd.GeoDataFrame([
            {"id": "r1", "damage_class": "intact", "length_m": 100,
             "geometry": LineString([(0, 0), (100, 0)])},
        ], crs=UTM_CRS)
        G = build_road_graph(roads)

        points = gpd.GeoDataFrame(
            [{"id": "p1", "name": "Test Point", "geometry": Point(5, 5)}],
            crs=UTM_CRS,
        )
        snapped = snap_points_to_graph(G, points, max_snap_distance=50)
        assert "p1" in snapped

    def test_too_far_not_snapped(self):
        from strand.network_graph.graph_builder import build_road_graph, snap_points_to_graph
        roads = gpd.GeoDataFrame([
            {"id": "r1", "damage_class": "intact", "length_m": 100,
             "geometry": LineString([(0, 0), (100, 0)])},
        ], crs=UTM_CRS)
        G = build_road_graph(roads)

        points = gpd.GeoDataFrame(
            [{"id": "p1", "name": "Far Point", "geometry": Point(0, 1000)}],
            crs=UTM_CRS,
        )
        snapped = snap_points_to_graph(G, points, max_snap_distance=50)
        assert "p1" not in snapped


class TestReachability:
    """Test Dijkstra-based settlement isolation classification."""

    def _make_simple_graph(self):
        """Create a simple graph: A — B — C with B-C severed."""
        G = nx.Graph()
        G.add_edge((0, 0), (100, 0), weight=100)  # A-B
        G.add_edge((100, 0), (200, 0), weight=100)  # B-C
        return G

    def test_connected_settlement(self):
        from strand.network_graph.reachability import classify_isolation
        G = self._make_simple_graph()
        settlements = {"s1": (0, 0)}
        hubs = {"h1": (200, 0)}
        results = classify_isolation(G, settlements, hubs)
        assert results["s1"]["status"] == "connected"
        assert results["s1"]["post_distance_m"] == pytest.approx(200.0)

    def test_isolated_settlement(self):
        from strand.network_graph.reachability import classify_isolation
        G = nx.Graph()
        G.add_node((0, 0))
        G.add_node((200, 0))  # Disconnected
        settlements = {"s1": (0, 0)}
        hubs = {"h1": (200, 0)}
        results = classify_isolation(G, settlements, hubs)
        assert results["s1"]["status"] == "isolated"

    def test_degraded_settlement(self):
        from strand.network_graph.reachability import classify_isolation
        G = self._make_simple_graph()
        # Make a long detour (weight > 3× pre-disaster)
        G.edges[(0, 0), (100, 0)]["weight"] = 1000  # Very long path
        settlements = {"s1": (0, 0)}
        hubs = {"h1": (200, 0)}
        pre_distances = {"s1": 200.0}  # Pre-disaster was 200m
        results = classify_isolation(G, settlements, hubs, pre_distances=pre_distances)
        assert results["s1"]["status"] == "degraded"

    def test_no_hubs(self):
        from strand.network_graph.reachability import classify_isolation
        G = self._make_simple_graph()
        settlements = {"s1": (0, 0)}
        hubs = {}
        results = classify_isolation(G, settlements, hubs)
        assert results["s1"]["status"] == "isolated"


class TestUrgencyScorer:
    """Test the urgency scoring formula."""

    def test_connected_gets_zero(self, settlements_gdf, flood_gdf):
        from strand.network_graph.urgency_scorer import compute_urgency_scores
        isolation = {
            "s1": {"status": "connected"},
            "s2": {"status": "connected"},
            "s3": {"status": "connected"},
            "s4": {"status": "connected"},
        }
        result = compute_urgency_scores(settlements_gdf, isolation, flood_gdf)
        assert all(result["urgency_score"] == 0.0)

    def test_isolated_gets_nonzero(self, settlements_gdf, flood_gdf):
        from strand.network_graph.urgency_scorer import compute_urgency_scores
        isolation = {
            "s1": {"status": "isolated"},
            "s2": {"status": "connected"},
            "s3": {"status": "connected"},
            "s4": {"status": "connected"},
        }
        result = compute_urgency_scores(settlements_gdf, isolation, flood_gdf)
        isolated = result[result["id"] == "s1"]
        if not isolated.empty:
            assert isolated.iloc[0]["urgency_score"] > 0

    def test_urgency_bounded_0_1(self, settlements_gdf, flood_gdf):
        from strand.network_graph.urgency_scorer import compute_urgency_scores
        isolation = {s: {"status": "isolated"} for s in ["s1", "s2", "s3", "s4"]}
        result = compute_urgency_scores(settlements_gdf, isolation, flood_gdf)
        assert all(result["urgency_score"] >= 0.0)
        assert all(result["urgency_score"] <= 1.0)
