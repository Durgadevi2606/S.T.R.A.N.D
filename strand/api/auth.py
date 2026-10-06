"""
S.T.R.A.N.D — API Authentication Middleware

Validates API keys from the X-API-Key request header.
"""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from strand.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Validate the API key from the request header.

    Raises HTTP 401 if the key is missing or invalid.
    """
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Include X-API-Key header.",
        )

    settings = get_settings()
    if api_key not in settings.strand_api_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )

    return api_key
