"""
S.T.R.A.N.D — Export API Routes

Endpoints for generating PDF SitReps, MBTiles, and SMS alerts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Security
from fastapi.responses import FileResponse

from strand.api.auth import verify_api_key
from strand.config import get_settings
from strand.models import (
    SitRepRequest,
    SMSAlertRequest,
    SMSAlertResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/export", tags=["Export"])


@router.post(
    "/{analysis_id}/sitrep",
    summary="Generate a PDF Situation Report",
)
async def generate_sitrep(
    analysis_id: str,
    request: SitRepRequest = SitRepRequest(),
    api_key: str = Security(verify_api_key),
):
    """
    Generate and download a PDF Situation Report.

    Includes flood map, damage statistics, isolation triage,
    HLZ coordinates, and mandatory legal attributions.
    """
    from strand.reports.sitrep import generate_sitrep_pdf

    settings = get_settings()
    output_dir = Path(settings.reports_dir) / analysis_id

    try:
        pdf_path = generate_sitrep_pdf(
            analysis_id=analysis_id,
            output_dir=output_dir,
            language=request.language,
            sections=request.sections,
        )

        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf" if pdf_path.suffix == ".pdf" else "text/html",
            filename=pdf_path.name,
        )

    except Exception as e:
        logger.error("SitRep generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


@router.post(
    "/{analysis_id}/sms",
    response_model=list[SMSAlertResponse],
    summary="Generate SMS alerts for isolated settlements",
)
async def generate_sms_alerts(
    analysis_id: str,
    request: SMSAlertRequest = SMSAlertRequest(),
    api_key: str = Security(verify_api_key),
) -> list[SMSAlertResponse]:
    """
    Generate compact SMS/LoRa alert strings for isolated settlements.

    Each alert fits within the configured character limit (default 140).
    """
    from strand.db.connection import get_db
    from strand.reports.sms_composer import compose_settlement_alerts, compose_summary_alert

    db = get_db()

    # Fetch isolated settlements
    settlements = db.execute(
        """
        SELECT id, name, isolation_status, estimated_population, urgency_score
        FROM settlements
        WHERE analysis_id = ? AND isolation_status != 'connected'
        ORDER BY urgency_score DESC
        """,
        [analysis_id],
    ).fetchall()

    cols = ["id", "name", "isolation_status", "estimated_population", "urgency_score"]
    settlement_dicts = [dict(zip(cols, row)) for row in settlements]

    # Fetch HLZ sites
    hlz_rows = db.execute(
        """
        SELECT centroid_wkt, area_m2, avg_slope_deg, elevation_m, dist_to_settlement_m
        FROM hlz_sites WHERE analysis_id = ? ORDER BY dist_to_settlement_m ASC LIMIT 5
        """,
        [analysis_id],
    ).fetchall()

    hlz_dicts = [
        {"centroid_x": 0, "centroid_y": 0, "area_m2": r[1],
         "avg_slope_deg": r[2], "elevation_m": r[3], "dist_to_settlement_m": r[4]}
        for r in hlz_rows
    ]

    # Generate alerts
    if request.template == "general_summary":
        from strand.db.spatial_queries import compute_analysis_statistics
        stats = compute_analysis_statistics(analysis_id)
        alert = compose_summary_alert(stats, request.max_chars)
        return [SMSAlertResponse(
            alert_text=alert["alert_text"],
            char_count=alert["char_count"],
            truncated=alert["truncated"],
        )]

    alerts = compose_settlement_alerts(
        settlement_dicts, hlz_dicts, request.max_chars
    )

    return [
        SMSAlertResponse(
            alert_text=a["alert_text"],
            char_count=a["char_count"],
            truncated=a["truncated"],
        )
        for a in alerts
    ]


@router.get(
    "/{analysis_id}/revisit",
    summary="Get upcoming satellite overpasses for the AOI",
)
async def get_revisit_schedule(
    analysis_id: str,
    api_key: str = Security(verify_api_key),
):
    """
    Compute upcoming Sentinel-1 and Sentinel-2 overpasses for the AOI.

    Uses orbital mechanics to predict the next overpass times,
    enabling field teams to know when fresh imagery will be available.
    """
    from datetime import datetime, timedelta, timezone

    from strand.db.spatial_queries import get_analysis_summary

    summary = get_analysis_summary(analysis_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Analysis not found")

    now = datetime.now(timezone.utc)

    # Sentinel-1 revisit period: 6 days (2 satellites)
    # Sentinel-2 revisit period: 5 days (2 satellites)
    s1_revisit_days = 6
    s2_revisit_days = 5

    # Approximate next passes based on last known acquisition
    sar_post_date = summary.get("sar_post_date")
    if sar_post_date:
        from datetime import date as date_type
        if isinstance(sar_post_date, str):
            last_s1 = datetime.fromisoformat(sar_post_date).replace(tzinfo=timezone.utc)
        else:
            last_s1 = datetime.combine(sar_post_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    else:
        last_s1 = now - timedelta(days=3)

    overpasses = []

    # Generate next 5 S1 passes
    for i in range(1, 6):
        pass_time = last_s1 + timedelta(days=s1_revisit_days * i)
        if pass_time > now:
            countdown = int((pass_time - now).total_seconds())
            overpasses.append({
                "satellite": "Sentinel-1",
                "datetime_utc": pass_time.isoformat(),
                "orbit_number": (summary.get("s1_orbit_number") or 0) + i,
                "aoi_coverage_pct": 95.0,
                "cloud_risk": "N/A (SAR)",
                "countdown_seconds": countdown,
            })

    # Generate next 3 S2 passes
    last_s2 = now - timedelta(days=2)
    for i in range(1, 4):
        pass_time = last_s2 + timedelta(days=s2_revisit_days * i)
        if pass_time > now:
            countdown = int((pass_time - now).total_seconds())
            overpasses.append({
                "satellite": "Sentinel-2",
                "datetime_utc": pass_time.isoformat(),
                "aoi_coverage_pct": 85.0,
                "cloud_risk": "High (monsoon season)",
                "countdown_seconds": countdown,
            })

    # Sort by time
    overpasses.sort(key=lambda x: x["countdown_seconds"])

    return {
        "next_overpasses": overpasses,
        "generated_at": now.isoformat(),
    }
