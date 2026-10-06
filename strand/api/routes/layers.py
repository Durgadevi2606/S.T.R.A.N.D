"""
S.T.R.A.N.D — GeoJSON Layer API Routes

Serves spatial layers as GeoJSON FeatureCollections for the map dashboard.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Security

from strand.api.auth import verify_api_key
from strand.db.spatial_queries import (
    get_bridges_geojson,
    get_flood_polygons_geojson,
    get_hlz_sites_geojson,
    get_ponding_zones_geojson,
    get_road_segments_geojson,
    get_settlements_geojson,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/layers", tags=["Layers"])


def _wrap_feature_collection(features: list[dict]) -> dict[str, Any]:
    """Wrap features in a GeoJSON FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": features,
    }


@router.get("/{analysis_id}/flood", summary="Flood extent polygons")
async def get_flood_layer(
    analysis_id: str,
    min_confidence: float = Query(0.0, ge=0, le=1),
    simplify: float = Query(0.0, ge=0, description="Simplification tolerance in meters"),
    api_key: str = Security(verify_api_key),
):
    """Return flood polygons as GeoJSON FeatureCollection."""
    features = get_flood_polygons_geojson(analysis_id, min_confidence, simplify)
    return _wrap_feature_collection(features)


@router.get("/{analysis_id}/roads", summary="Road segments with damage class")
async def get_roads_layer(
    analysis_id: str,
    damage_class: str = Query("all", description="Filter: intact, partially_flooded, severed, all"),
    highway_type: str = Query("all", description="Filter by OSM highway type"),
    api_key: str = Security(verify_api_key),
):
    """Return road segments as GeoJSON with damage classification."""
    features = get_road_segments_geojson(analysis_id, damage_class, highway_type)
    return _wrap_feature_collection(features)


@router.get("/{analysis_id}/bridges", summary="Bridges with damage class")
async def get_bridges_layer(
    analysis_id: str,
    damage_class: str = Query("all"),
    api_key: str = Security(verify_api_key),
):
    """Return bridges as GeoJSON with damage classification."""
    features = get_bridges_geojson(analysis_id, damage_class)
    return _wrap_feature_collection(features)


@router.get("/{analysis_id}/settlements", summary="Settlements with isolation status")
async def get_settlements_layer(
    analysis_id: str,
    isolation_status: str = Query("all", description="Filter: isolated, degraded, connected, all"),
    sort_by: str = Query("urgency_score"),
    sort_order: str = Query("desc"),
    api_key: str = Security(verify_api_key),
):
    """Return settlements as GeoJSON with isolation and urgency scores."""
    features = get_settlements_geojson(analysis_id, isolation_status, sort_by, sort_order)
    return _wrap_feature_collection(features)


@router.get("/{analysis_id}/hlz", summary="Helicopter Landing Zones")
async def get_hlz_layer(
    analysis_id: str,
    max_slope: float = Query(5.0, ge=0, le=45),
    min_area: float = Query(900.0, ge=100),
    api_key: str = Security(verify_api_key),
):
    """Return HLZ candidate sites as GeoJSON."""
    features = get_hlz_sites_geojson(analysis_id, max_slope, min_area)
    return _wrap_feature_collection(features)


@router.get("/{analysis_id}/ponding", summary="Ponding / debris dam zones")
async def get_ponding_layer(
    analysis_id: str,
    api_key: str = Security(verify_api_key),
):
    """Return ponding risk zones as GeoJSON."""
    features = get_ponding_zones_geojson(analysis_id)
    return _wrap_feature_collection(features)
