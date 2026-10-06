"""
S.T.R.A.N.D — Settlement Urgency Scorer

Computes a normalized urgency score (0–1) for each settlement to
prioritize rescue and relief dispatch.

Formula:
    urgency = w₁ × pop_norm + w₂ × flood_prox_norm + w₃ × clinic_penalty

Where:
- pop_norm: Normalized estimated population (higher → more urgent)
- flood_prox_norm: Normalized proximity to flood edge (closer → more urgent)
- clinic_penalty: 1.0 if settlement has no reachable health clinic, 0.0 otherwise
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from strand.config import (
    URGENCY_W_CLINIC_PENALTY,
    URGENCY_W_FLOOD_PROXIMITY,
    URGENCY_W_POPULATION,
)

logger = logging.getLogger(__name__)


def compute_urgency_scores(
    settlements_gdf: gpd.GeoDataFrame,
    isolation_results: dict[str, dict[str, Any]],
    flood_gdf: gpd.GeoDataFrame,
    w_population: float = URGENCY_W_POPULATION,
    w_flood_proximity: float = URGENCY_W_FLOOD_PROXIMITY,
    w_clinic_penalty: float = URGENCY_W_CLINIC_PENALTY,
) -> gpd.GeoDataFrame:
    """
    Compute urgency scores for all settlements.

    Only ISOLATED and DEGRADED settlements receive urgency scores.
    CONNECTED settlements get urgency = 0.

    Args:
        settlements_gdf: GeoDataFrame with settlement geometries and population.
        isolation_results: Dict from classify_isolation().
        flood_gdf: GeoDataFrame of flood polygons (for proximity calculation).
        w_population: Weight for population factor.
        w_flood_proximity: Weight for flood proximity factor.
        w_clinic_penalty: Weight for clinic absence penalty.

    Returns:
        GeoDataFrame with added 'urgency_score' column (0.0 to 1.0).
    """
    logger.info("Computing urgency scores for %d settlements...", len(settlements_gdf))

    settlements = settlements_gdf.copy()

    # Extract population values
    pop_col = "estimated_population"
    if pop_col not in settlements.columns:
        settlements[pop_col] = 0

    populations = settlements[pop_col].fillna(0).values.astype(float)

    # Normalize population (0–1 via min-max)
    pop_max = populations.max() if populations.max() > 0 else 1.0
    pop_norm = populations / pop_max

    # Compute flood proximity for each settlement
    if not flood_gdf.empty:
        flood_union = flood_gdf.geometry.unary_union
        flood_distances = settlements.geometry.apply(
            lambda geom: geom.distance(flood_union) if geom is not None else float("inf")
        ).values
    else:
        flood_distances = np.full(len(settlements), float("inf"))

    # Normalize flood proximity (closer = higher urgency)
    # Use inverse: prox = 1 - (distance / max_distance)
    max_dist = flood_distances[flood_distances < float("inf")].max() if np.any(flood_distances < float("inf")) else 1.0
    if max_dist == 0:
        max_dist = 1.0
    flood_prox_norm = np.where(
        flood_distances < float("inf"),
        1.0 - np.clip(flood_distances / max_dist, 0, 1),
        0.0,
    )

    # Compute scores
    urgency_scores = []

    for i, (idx, settlement) in enumerate(settlements.iterrows()):
        s_id = settlement.get("id", str(idx))
        iso_result = isolation_results.get(s_id, {})
        status = iso_result.get("status", "connected")

        if status == "connected":
            urgency_scores.append(0.0)
            continue

        # Population component
        pop_score = pop_norm[i]

        # Flood proximity component
        prox_score = flood_prox_norm[i]

        # Clinic penalty (1.0 if no reachable clinic)
        has_clinic = settlement.get("has_clinic", False)
        clinic_score = 0.0 if has_clinic else 1.0

        # Weighted sum
        urgency = (
            w_population * pop_score
            + w_flood_proximity * prox_score
            + w_clinic_penalty * clinic_score
        )

        # Boost for ISOLATED vs DEGRADED
        if status == "isolated":
            urgency = min(urgency * 1.25, 1.0)  # 25% boost for full isolation

        urgency_scores.append(round(urgency, 4))

    settlements["urgency_score"] = urgency_scores

    # Log top priority settlements
    non_zero = settlements[settlements["urgency_score"] > 0].sort_values(
        "urgency_score", ascending=False
    )

    if not non_zero.empty:
        logger.info("Top priority settlements:")
        for _, row in non_zero.head(5).iterrows():
            name = row.get("name", "unnamed")
            score = row["urgency_score"]
            pop = row.get("estimated_population", "?")
            logger.info("  %s: urgency=%.3f, pop=%s", name, score, pop)

    logger.info(
        "Urgency scores computed: %d scored, max=%.3f",
        (settlements["urgency_score"] > 0).sum(),
        settlements["urgency_score"].max(),
    )

    return settlements
