"""
S.T.R.A.N.D — Analysis API Routes

Endpoints for triggering, monitoring, and retrieving analysis results.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Security

from strand.api.auth import verify_api_key
from strand.db.connection import get_db
from strand.db.spatial_queries import (
    compute_analysis_statistics,
    get_analysis_summary,
    get_analysis_warnings,
)
from strand.models import (
    AnalysisCreatedResponse,
    AnalysisListResponse,
    AnalysisListItem,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSummary,
    AnalysisStatus,
    AnalysisMetadata,
    ErrorResponse,
    ErrorDetail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["Analysis"])


@router.post(
    "",
    response_model=AnalysisCreatedResponse,
    status_code=202,
    summary="Trigger a new flood damage analysis",
)
async def create_analysis(
    request: AnalysisRequest,
    api_key: str = Security(verify_api_key),
) -> AnalysisCreatedResponse:
    """
    Submit a new analysis request.

    The analysis runs asynchronously via Celery. Monitor progress
    via the WebSocket endpoint or poll GET /analysis/{id}.
    """
    analysis_id = str(uuid.uuid4())

    try:
        from strand.pipeline.tasks import run_analysis_task

        # Dispatch Celery task
        run_analysis_task.delay(request.model_dump(mode="json"), analysis_id)

        logger.info(
            "Analysis queued: id=%s, aoi=%.4f,%.4f-%.4f,%.4f, date=%s",
            analysis_id,
            request.aoi_bbox.west, request.aoi_bbox.south,
            request.aoi_bbox.east, request.aoi_bbox.north,
            request.disaster_date,
        )

        return AnalysisCreatedResponse(
            analysis_id=analysis_id,
            status=AnalysisStatus.QUEUED,
            estimated_duration_min=43,
            websocket_url=f"/ws/analysis/{analysis_id}",
            created_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        logger.error("Failed to queue analysis: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to queue analysis: {e}",
        )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Get analysis status and results",
)
async def get_analysis(
    analysis_id: str,
    api_key: str = Security(verify_api_key),
) -> AnalysisResponse:
    """Retrieve the current status and results of an analysis."""
    summary = get_analysis_summary(analysis_id)

    if summary is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    warnings = get_analysis_warnings(analysis_id)

    return AnalysisResponse(
        analysis_id=analysis_id,
        status=AnalysisStatus(summary["status"]),
        progress_pct=summary.get("progress_pct", 0),
        current_phase=summary.get("current_phase"),
        summary=AnalysisSummary(
            flood_area_km2=summary.get("flood_area_km2"),
            roads_total_km=summary.get("roads_total_km"),
            roads_severed_km=summary.get("roads_severed_km"),
            roads_partially_flooded_km=summary.get("roads_partial_km"),
            bridges_total=summary.get("bridges_total"),
            bridges_destroyed=summary.get("bridges_destroyed"),
            bridges_damaged=summary.get("bridges_damaged"),
            buildings_total=summary.get("buildings_total"),
            buildings_submerged=summary.get("buildings_submerged"),
            buildings_flood_contact=summary.get("buildings_contact"),
            settlements_total=summary.get("settlements_total"),
            settlements_isolated=summary.get("settlements_isolated"),
            settlements_degraded=summary.get("settlements_degraded"),
            hlz_candidates=summary.get("hlz_count"),
            ponding_zones=summary.get("ponding_count"),
        ) if summary["status"] == "complete" else None,
        metadata=AnalysisMetadata(
            sar_pre_date=summary.get("sar_pre_date"),
            sar_post_date=summary.get("sar_post_date"),
            orbit_number=summary.get("s1_orbit_number"),
            orbit_direction=summary.get("orbit_direction"),
            s2_available=summary.get("s2_available", False),
            osm_snapshot=summary.get("osm_snapshot_ts"),
            utm_epsg=summary.get("utm_epsg"),
        ),
        warnings=warnings,
        created_at=summary.get("created_at", datetime.now(timezone.utc)),
        completed_at=summary.get("completed_at"),
    )


@router.get(
    "",
    response_model=AnalysisListResponse,
    summary="List all analyses",
)
async def list_analyses(
    api_key: str = Security(verify_api_key),
) -> AnalysisListResponse:
    """List all analyses, newest first."""
    db = get_db()
    rows = db.execute(
        "SELECT id, status, disaster_date, flood_area_km2, created_at "
        "FROM analyses ORDER BY created_at DESC"
    ).fetchall()

    analyses = [
        AnalysisListItem(
            analysis_id=row[0],
            status=AnalysisStatus(row[1]),
            disaster_date=row[2],
            flood_area_km2=row[3],
            created_at=row[4],
        )
        for row in rows
    ]

    return AnalysisListResponse(total=len(analyses), analyses=analyses)


@router.delete(
    "/{analysis_id}",
    status_code=204,
    summary="Delete an analysis",
)
async def delete_analysis(
    analysis_id: str,
    api_key: str = Security(verify_api_key),
):
    """Delete an analysis and all associated data."""
    db = get_db()
    summary = get_analysis_summary(analysis_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Delete from all tables
    tables = [
        "analysis_warnings", "copilot_queries", "pipeline_logs",
        "flow_paths", "ponding_zones", "hlz_sites",
        "settlement_hub_routes", "hub_nodes", "settlements",
        "buildings", "bridges", "road_segments",
        "flood_polygons", "analyses",
    ]
    for table in tables:
        db.execute(f"DELETE FROM {table} WHERE analysis_id = ?", [analysis_id])
    db.execute("DELETE FROM analyses WHERE id = ?", [analysis_id])

    logger.info("Deleted analysis %s", analysis_id)
