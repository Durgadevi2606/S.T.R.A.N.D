"""
S.T.R.A.N.D — Road Network Graph Builder

Builds a NetworkX graph from OSM road segments, incorporating flood damage
as edge weights. Snaps settlement and hub nodes to nearest road nodes.

The graph is the foundation for all reachability and isolation analysis.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

from strand.config import SETTLEMENT_SNAP_DISTANCE_M

logger = logging.getLogger(__name__)


def build_road_graph(
    roads_gdf: gpd.GeoDataFrame,
) -> nx.Graph:
    """
    Build a weighted, undirected graph from classified road segments.

    Each road segment becomes one or more edges. Nodes are created at
    road intersections (shared coordinates between segments).

    Edge weights:
    - INTACT roads: weight = length_m (normal travel cost)
    - PARTIALLY_FLOODED: weight = length_m × 5 (degraded but passable)
    - SEVERED: weight = ∞ (impassable — edge removed from graph)

    Args:
        roads_gdf: GeoDataFrame with road geometries, damage_class, and length_m.

    Returns:
        NetworkX Graph with:
        - Nodes: (lon, lat) coordinates at road endpoints
        - Edges: weight, length_m, damage_class, road_id, highway_type
    """
    logger.info("Building road network graph from %d segments...", len(roads_gdf))

    G = nx.Graph()

    intact_edges = 0
    degraded_edges = 0
    severed_count = 0

    for idx, road in roads_gdf.iterrows():
        damage_class = road.get("damage_class", "intact")

        # Skip severed roads (they are impassable)
        if damage_class == "severed":
            severed_count += 1
            continue

        geom = road.geometry
        length_m = road.get("length_m", geom.length)

        # Weight multiplier based on damage
        if damage_class == "partially_flooded":
            weight = length_m * 5.0  # 5× penalty for degraded road
            degraded_edges += 1
        else:
            weight = length_m
            intact_edges += 1

        # Extract endpoints for nodes
        coords = list(geom.coords)
        if len(coords) < 2:
            continue

        start = _round_coord(coords[0])
        end = _round_coord(coords[-1])

        # Add nodes with coordinate attributes
        G.add_node(start, x=start[0], y=start[1])
        G.add_node(end, x=end[0], y=end[1])

        # Add edge
        G.add_edge(
            start, end,
            weight=weight,
            length_m=length_m,
            damage_class=damage_class,
            road_id=road.get("id", str(idx)),
            highway_type=road.get("highway_type", "unknown"),
            osm_id=road.get("osm_id", None),
        )

        # Also add intermediate nodes for long segments (for better snapping)
        if len(coords) > 2 and length_m > 500:
            prev_node = start
            cumulative = 0.0
            for i in range(1, len(coords) - 1):
                curr = _round_coord(coords[i])
                seg_len = Point(coords[i - 1]).distance(Point(coords[i]))
                cumulative += seg_len

                if damage_class == "partially_flooded":
                    seg_weight = seg_len * 5.0
                else:
                    seg_weight = seg_len

                G.add_node(curr, x=curr[0], y=curr[1])
                G.add_edge(
                    prev_node, curr,
                    weight=seg_weight,
                    length_m=seg_len,
                    damage_class=damage_class,
                    road_id=road.get("id", str(idx)),
                    highway_type=road.get("highway_type", "unknown"),
                )
                prev_node = curr

            # Final segment to end
            seg_len = Point(coords[-2]).distance(Point(coords[-1]))
            seg_weight = seg_len * 5.0 if damage_class == "partially_flooded" else seg_len
            G.add_edge(
                prev_node, end,
                weight=seg_weight,
                length_m=seg_len,
                damage_class=damage_class,
                road_id=road.get("id", str(idx)),
                highway_type=road.get("highway_type", "unknown"),
            )

    # Count connected components
    n_components = nx.number_connected_components(G)

    logger.info(
        "Road graph built: %d nodes, %d edges, %d components",
        G.number_of_nodes(), G.number_of_edges(), n_components,
    )
    logger.info(
        "  Edges: %d intact, %d degraded, %d severed (removed)",
        intact_edges, degraded_edges, severed_count,
    )

    return G


def snap_points_to_graph(
    G: nx.Graph,
    points_gdf: gpd.GeoDataFrame,
    max_snap_distance: float = SETTLEMENT_SNAP_DISTANCE_M,
    label_column: str = "name",
) -> dict[str, tuple[float, float]]:
    """
    Snap point features (settlements, hubs) to the nearest road graph node.

    For each point, finds the nearest node within max_snap_distance.
    Points that cannot be snapped are flagged with a warning.

    Args:
        G: Road network graph.
        points_gdf: GeoDataFrame of point features.
        max_snap_distance: Maximum snap distance in CRS units (meters for UTM).
        label_column: Column name used for logging/identification.

    Returns:
        Dict mapping point ID to the graph node it was snapped to.
        Keys are from the GeoDataFrame index; values are (x, y) node tuples.
    """
    if points_gdf.empty or G.number_of_nodes() == 0:
        return {}

    # Build KD-tree of graph nodes for fast nearest-neighbor lookup
    node_list = list(G.nodes())
    node_coords = np.array([[n[0], n[1]] for n in node_list])

    from scipy.spatial import KDTree
    tree = KDTree(node_coords)

    snapped = {}
    unsnapped = []

    for idx, point in points_gdf.iterrows():
        pt_coord = np.array([point.geometry.x, point.geometry.y])
        dist, nearest_idx = tree.query(pt_coord)

        label = point.get(label_column, str(idx)) or str(idx)
        point_id = point.get("id", str(idx))

        if dist <= max_snap_distance:
            snapped_node = node_list[nearest_idx]
            snapped[point_id] = snapped_node
            logger.debug(
                "  Snapped '%s' to graph node (dist=%.0fm)", label, dist
            )
        else:
            unsnapped.append((label, dist))

    if unsnapped:
        logger.warning(
            "%d points could not be snapped (>%.0fm from road):",
            len(unsnapped), max_snap_distance,
        )
        for name, dist in unsnapped[:5]:
            logger.warning("  '%s': %.0fm from nearest road", name, dist)

    logger.info(
        "Snapped %d/%d points to graph (max_dist=%.0fm)",
        len(snapped), len(points_gdf), max_snap_distance,
    )

    return snapped


def build_pre_disaster_graph(roads_gdf: gpd.GeoDataFrame) -> nx.Graph:
    """
    Build a graph with all roads treated as INTACT (pre-disaster baseline).

    Used to compute pre-disaster shortest distances for degradation comparison.
    """
    roads_copy = roads_gdf.copy()
    roads_copy["damage_class"] = "intact"
    return build_road_graph(roads_copy)


def _round_coord(coord: tuple, precision: int = 1) -> tuple[float, float]:
    """
    Round coordinates to reduce floating-point node duplication.

    At 1 decimal place in UTM meters, this gives ~0.1m precision
    which is sufficient for node identity.
    """
    if len(coord) >= 2:
        return (round(coord[0], precision), round(coord[1], precision))
    return (round(coord[0], precision), 0.0)
