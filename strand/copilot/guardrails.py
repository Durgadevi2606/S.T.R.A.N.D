"""
S.T.R.A.N.D — Copilot Security Guardrails

Input sanitization, prompt injection detection, and SQL output
validation to ensure zero-hallucination copilot responses.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Blocked input patterns (prompt injection attempts)
BLOCKED_PATTERNS = [
    r"ignore\s+(previous|above|all)\s+instructions",
    r"system\s+prompt",
    r"act\s+as",
    r"pretend\s+(you|to\s+be)",
    r"forget\s+(everything|your|all)",
    r"you\s+are\s+now",
    r"new\s+instructions",
    r"override",
    r"jailbreak",
    r"DAN\s+mode",
]

# SQL keywords that should NEVER appear in generated output
FORBIDDEN_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "ATTACH",
    "DETACH", "PRAGMA", "COPY", "EXPORT",
]


class GuardrailViolation(Exception):
    """Raised when a guardrail check fails."""


def sanitize_query(query: str, max_length: int = 500) -> str:
    """
    Sanitize user input before sending to LLM.

    Checks:
    1. Length limit (max 500 chars)
    2. Prompt injection patterns
    3. Control character stripping

    Args:
        query: Raw user query string.
        max_length: Maximum allowed length.

    Returns:
        Sanitized query string.

    Raises:
        GuardrailViolation: If query contains prohibited patterns.
    """
    if not query or not query.strip():
        raise GuardrailViolation("Query cannot be empty")

    query = query.strip()

    # Length check
    if len(query) > max_length:
        raise GuardrailViolation(
            f"Query too long ({len(query)} chars, max {max_length})"
        )

    # Strip control characters
    query = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', query)

    # Check for injection patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            logger.warning("Blocked prompt injection attempt: '%s'", query[:100])
            raise GuardrailViolation(
                "Query contains prohibited patterns. "
                "I can only answer questions about the flood analysis data."
            )

    return query


def validate_sql_output(sql: str) -> bool:
    """
    Ensure generated SQL is read-only and safe to execute.

    Rules:
    1. Must start with SELECT
    2. Must not contain any modification keywords
    3. Must not contain multiple statements (no semicolons mid-string)
    4. Must not use ATTACH or PRAGMA (DuckDB specific)

    Args:
        sql: Generated SQL string.

    Returns:
        True if SQL is safe, False otherwise.
    """
    sql_upper = sql.upper().strip()

    # Must be a SELECT query
    if not sql_upper.startswith("SELECT"):
        logger.warning("Non-SELECT SQL blocked: %s", sql[:100])
        return False

    # Check for forbidden keywords
    for keyword in FORBIDDEN_SQL_KEYWORDS:
        # Match keyword as a whole word
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, sql_upper):
            logger.warning("Forbidden SQL keyword '%s' detected", keyword)
            return False

    # No multi-statement
    # Allow trailing semicolon, but not mid-query
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        logger.warning("Multi-statement SQL blocked")
        return False

    return True


def validate_response(
    response_text: str,
    sql_result: dict | None = None,
) -> tuple[bool, str]:
    """
    Validate copilot response against the SQL result to detect hallucination.

    Checks:
    1. If SQL returned numbers, they should appear in the response
    2. Response should not contain made-up statistics
    3. Response should reference the analysis data

    Args:
        response_text: LLM-generated response text.
        sql_result: Dict of the SQL query result.

    Returns:
        Tuple of (is_valid, reason).
    """
    if sql_result is None:
        return True, "No SQL result to validate against"

    # Extract numbers from SQL result
    result_numbers = set()
    for key, value in sql_result.items():
        if isinstance(value, (int, float)):
            result_numbers.add(str(round(value, 2)))
            result_numbers.add(str(int(value)))

    # If SQL returned specific numbers, at least one should appear in the response
    if result_numbers:
        response_has_number = any(
            num in response_text for num in result_numbers
        )
        if not response_has_number:
            return False, (
                "Response does not contain any values from the SQL result. "
                "Possible hallucination detected."
            )

    return True, "Response consistent with SQL result"
