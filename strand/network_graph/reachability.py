"""
S.T.R.A.N.D — Settlement Reachability & Isolation Analysis

Runs Dijkstra's shortest path algorithm on the pre- and post-disaster
road graphs to classify settlements by connectivity status.

Classification:
- ISOLATED: No path exists to any hub node (hospital/supply depot)
- DEGRADED: Path exists but is ≥3× longer than pre-disaster
- CONNECTED: Path exists and is < 3× pre-disaster distance
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from strand.config import DEGRADED_PATH_MULTIPLIER

logger = logging.getLogger(__name__)


def classify_isolation(
    post_graph: nx.Graph,
    settlement_nodes: dict[str, tuple[float, float]],
    hub_nodes: dict[str, tuple[float, float]],
    pre_distances: dict[str, float] | None = None,
    degraded_multiplier: float = DEGRADED_PATH_MULTIPLIER,
) -> dict[str, dict[str, Any]]:
    """
    Classify settlement isolation status using graph reachability.

    Algorithm:
    1. For each settlement node, compute shortest path to nearest hub.
    2. Compare post-disaster distance to pre-disaster distance.
    3. Classify based on ratio:
       - No path → ISOLATED
       - Distance ≥ 3× pre-disaster → DEGRADED
       - Distance < 3× pre-disaster → CONNECTED

    Args:
        post_graph: Post-disaster road graph (severed edges removed).
        settlement_nodes: Dict mapping settlement_id → graph node tuple.
        hub_nodes: Dict mapping hub_id → graph node tuple.
        pre_distances: Optional dict of pre-disaster shortest distances
                       (settlement_id → meters). If None, all pre-distances
                       are assumed to be the post-distance (CONNECTED/ISOLATED only).
        degraded_multiplier: Ratio threshold for DEGRADED classification.

    Returns:
        Dict mapping settlement_id to result dict with:
        - status: 'isolated', 'degraded', or 'connected'
        - post_distance_m: Shortest post-disaster distance to nearest hub
        - pre_distance_m: Pre-disaster distance (if available)
        - nearest_hub_id: ID of the nearest reachable hub
        - distance_ratio: post/pre distance ratio
        - path_nodes: Shortest path node list (if reachable)
    """
    logger.info(
        "Classifying isolation: %d settlements, %d hubs",
        len(settlement_nodes), len(hub_nodes),
    )

    if not hub_nodes:
        logger.warning("No hub nodes — all settlements classified as isolated")
        return {
            sid: {
                "status": "isolated",
                "post_distance_m": float("inf"),
                "pre_distance_m": None,
                "nearest_hub_id": None,
                "distance_ratio": float("inf"),
                "path_nodes": [],
            }
            for sid in settlement_nodes
        }

    # Compute all-pairs shortest path from hub nodes
    hub_node_set = set(hub_nodes.values())

    results = {}

    for s_id, s_node in settlement_nodes.items():
        # Check if the settlement node exists in the graph
        if s_node not in post_graph:
            logger.warning("Settlement %s node not in graph, marked as isolated", s_id)
            results[s_id] = {
                "status": "isolated",
                "post_distance_m": float("inf"),
                "pre_distance_m": pre_distances.get(s_id) if pre_distances else None,
                "nearest_hub_id": None,
                "distance_ratio": float("inf"),
                "path_nodes": [],
            }
            continue

        # Find shortest distance to any hub
        best_distance = float("inf")
        best_hub_id = None
        best_path = []

        for h_id, h_node in hub_nodes.items():
            if h_node not in post_graph:
                continue

            try:
                distance = nx.dijkstra_path_length(
                    post_graph, s_node, h_node, weight="weight"
                )
                if distance < best_distance:
                    best_distance = distance
                    best_hub_id = h_id
                    best_path = nx.dijkstra_path(
                        post_graph, s_node, h_node, weight="weight"
                    )
            except nx.NetworkXNoPath:
                continue
            except nx.NodeNotFound:
                continue

        # Classify based on pre/post distance comparison
        pre_dist = pre_distances.get(s_id) if pre_distances else None

        if best_distance == float("inf"):
            status = "isolated"
            distance_ratio = float("inf")
        elif pre_dist is not None and pre_dist > 0:
            distance_ratio = best_distance / pre_dist
            if distance_ratio >= degraded_multiplier:
                status = "degraded"
            else:
                status = "connected"
        else:
            # No pre-disaster reference — assume connected if reachable
            status = "connected"
            distance_ratio = 1.0

        results[s_id] = {
            "status": status,
            "post_distance_m": round(best_distance, 1) if best_distance != float("inf") else float("inf"),
            "pre_distance_m": round(pre_dist, 1) if pre_dist else None,
            "nearest_hub_id": best_hub_id,
            "distance_ratio": round(distance_ratio, 2) if distance_ratio != float("inf") else float("inf"),
            "path_nodes": best_path,
        }

    # Summary statistics
    isolated = sum(1 for r in results.values() if r["status"] == "isolated")
    degraded = sum(1 for r in results.values() if r["status"] == "degraded")
    connected = sum(1 for r in results.values() if r["status"] == "connected")

    logger.info(
        "Isolation classification: %d isolated, %d degraded, %d connected",
        isolated, degraded, connected,
    )

    return results


def compute_pre_disaster_distances(
    pre_graph: nx.Graph,
    settlement_nodes: dict[str, tuple[float, float]],
    hub_nodes: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """
    Compute shortest distances from each settlement to nearest hub
    on the pre-disaster (fully intact) road graph.

    Args:
        pre_graph: Pre-disaster road graph (all roads intact).
        settlement_nodes: Dict mapping settlement_id → graph node.
        hub_nodes: Dict mapping hub_id → graph node.

    Returns:
        Dict mapping settlement_id → shortest distance to nearest hub (meters).
    """
    logger.info("Computing pre-disaster baseline distances...")

    distances = {}

    for s_id, s_node in settlement_nodes.items():
        if s_node not in pre_graph:
            distances[s_id] = float("inf")
            continue

        best = float("inf")
        for h_id, h_node in hub_nodes.items():
            if h_node not in pre_graph:
                continue
            try:
                d = nx.dijkstra_path_length(pre_graph, s_node, h_node, weight="weight")
                best = min(best, d)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

        distances[s_id] = best

    reachable = sum(1 for d in distances.values() if d < float("inf"))
    logger.info(
        "Pre-disaster: %d/%d settlements reachable from hubs",
        reachable, len(distances),
    )

    return distances


def extract_shortest_path_geometry(
    G: nx.Graph,
    path_nodes: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Extract the coordinate geometry of a shortest path for visualization.

    Args:
        G: The road graph.
        path_nodes: List of (x, y) node tuples from Dijkstra.

    Returns:
        List of (x, y) coordinates forming the path LineString.
    """
    if len(path_nodes) < 2:
        return path_nodes

    coords = [(n[0], n[1]) for n in path_nodes]
    return coords
