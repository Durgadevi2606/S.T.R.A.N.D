"""
S.T.R.A.N.D — Copilot API Route

Endpoint for the bilingual NL-to-SQL copilot.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Security

from strand.api.auth import verify_api_key
from strand.models import CopilotQueryRequest, CopilotQueryResponse, SQLCitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/copilot", tags=["Copilot"])


@router.post(
    "/{analysis_id}/query",
    response_model=CopilotQueryResponse,
    summary="Ask the bilingual copilot a question",
)
async def copilot_query(
    analysis_id: str,
    request: CopilotQueryRequest,
    api_key: str = Security(verify_api_key),
) -> CopilotQueryResponse:
    """
    Query the bilingual copilot with a natural language question.

    The copilot generates SQL, executes it against the analysis database,
    and returns a grounded response with the SQL citation.

    Supports English ('en') and Nepali ('ne').
    """
    from strand.copilot.engine import CopilotEngine

    engine = CopilotEngine(analysis_id=analysis_id)

    try:
        result = await engine.answer(
            query=request.query,
            language=request.language,
        )

        citation = None
        if result.get("citation"):
            from datetime import datetime, timezone

            citation = SQLCitation(
                sql=result["citation"]["sql"],
                raw_result=result["citation"]["raw_result"],
                executed_at=datetime.now(timezone.utc),
            )

        return CopilotQueryResponse(
            answer=result["answer"],
            language=result["language"],
            citation=citation,
            hallucination_check=result.get("hallucination_check", True),
            confidence=result.get("confidence", "high"),
        )

    except Exception as e:
        logger.error("Copilot error: %s", e)
        raise HTTPException(status_code=500, detail=f"Copilot error: {e}")
