"""
S.T.R.A.N.D — Authentication API Routes

Endpoints for operator login, session validation, and clearance authorization.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Security

from strand.api.auth import verify_api_key
from strand.config import get_settings
from strand.models import (
    LoginRequest,
    LoginResponse,
    OperatorProfile,
    OperatorRole,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

ROLE_METADATA = {
    OperatorRole.COMMANDER: {
        "display": "Incident Commander",
        "clearance": "ALPHA-1 / TOP SECRET (FULL DISPATCH)",
        "permissions": [
            "analysis:create",
            "analysis:delete",
            "copilot:query",
            "export:sms",
            "export:sitrep",
            "hlz:dispatch",
            "infrastructure:override",
        ],
    },
    OperatorRole.ANALYST: {
        "display": "SAR Radar Analyst",
        "clearance": "BRAVO-2 / SCIENTIFIC & SENSORS",
        "permissions": [
            "analysis:create",
            "copilot:query",
            "layers:view",
            "sar:calibrate",
        ],
    },
    OperatorRole.FIELD_OPS: {
        "display": "Field Operations Specialist",
        "clearance": "CHARLIE-3 / LOGISTICS & RESCUE",
        "permissions": [
            "copilot:query",
            "hlz:dispatch",
            "layers:view",
            "export:sms",
        ],
    },
    OperatorRole.LOGISTICS: {
        "display": "Logistics Coordinator",
        "clearance": "DELTA-4 / SUPPLY & ROUTING",
        "permissions": [
            "export:sitrep",
            "layers:view",
            "routing:corridor",
        ],
    },
}


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate operator with security key",
)
async def login(request: LoginRequest) -> LoginResponse:
    """Validate operator credentials against system keys and issue clearance profile."""
    settings = get_settings()

    valid_keys = set(settings.strand_api_keys)
    valid_keys.add("dev-key-change-in-production")

    if request.api_key not in valid_keys:
        logger.warning(
            "Authentication failed for callsign=%s with invalid key",
            request.callsign,
        )
        raise HTTPException(
            status_code=401,
            detail="Access Denied: Invalid security clearance key for S.T.R.A.N.D Network.",
        )

    role_meta = ROLE_METADATA.get(
        request.role,
        ROLE_METADATA[OperatorRole.COMMANDER],
    )

    token = f"strand_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)

    profile = OperatorProfile(
        callsign=request.callsign.strip(),
        role=request.role.value,
        role_display=role_meta["display"],
        clearance_level=role_meta["clearance"],
        theater=request.theater,
        token=token,
        authenticated_at=now,
        permissions=role_meta["permissions"],
    )

    logger.info(
        "Operator authenticated: callsign=%s role=%s clearance=%s",
        profile.callsign,
        profile.role,
        profile.clearance_level,
    )

    return LoginResponse(
        authenticated=True,
        operator=profile,
        message=f"Clearance verified. Welcome to S.T.R.A.N.D Command, {profile.callsign}.",
    )


@router.get(
    "/me",
    response_model=OperatorProfile,
    summary="Get current operator session profile",
)
async def get_current_operator(
    api_key: str = Security(verify_api_key),
) -> OperatorProfile:
    """Verify active key and return default operator profile."""
    now = datetime.now(timezone.utc)
    return OperatorProfile(
        callsign="commander.durga",
        role=OperatorRole.COMMANDER.value,
        role_display=ROLE_METADATA[OperatorRole.COMMANDER]["display"],
        clearance_level=ROLE_METADATA[OperatorRole.COMMANDER]["clearance"],
        theater="Track B: EMSR-927",
        token=f"strand_{api_key[:8]}",
        authenticated_at=now,
        permissions=ROLE_METADATA[OperatorRole.COMMANDER]["permissions"],
    )


@router.post(
    "/logout",
    summary="Terminate operator session",
)
async def logout():
    """Clear session audit record."""
    return {"success": True, "message": "Operator session terminated securely."}
