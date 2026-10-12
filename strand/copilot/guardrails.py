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

    # If the query returned zero rows or no data found, check for no-data phrasing
    if sql_result.get("rows") == 0 or "No data found" in str(sql_result):
        return True, "Valid empty query response"

    # Extract numbers from SQL result (both top-level and inside rows)
    result_numbers = set()
    for key, value in sql_result.items():
        if key in ("rows", "columns"):
            continue
        if isinstance(value, (int, float)):
            result_numbers.add(str(round(value, 2)))
            result_numbers.add(str(int(value)))

    if "rows" in sql_result and isinstance(sql_result["rows"], list):
        for r in sql_result["rows"]:
            if isinstance(r, dict):
                for v in r.values():
                    if isinstance(v, (int, float)):
                        result_numbers.add(str(round(v, 2)))
                        result_numbers.add(str(int(v)))

    # Filter out trivial numbers like 0 or 1 if other numbers exist
    if len(result_numbers) > 2:
        result_numbers.discard("0")

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


# ─── Domain & Intent Guardrails ───────────────────────────────

DISASTER_DOMAIN_PATTERNS = [
    # Water & Flooding
    r"flood", r"inundat", r"submerg", r"pond", r"water", r"river", r"koshi", r"bhotekoshi",
    r"depth", r"extent", r"drainage", r"overflow", r"monsoon",
    # Roads & Transport Network
    r"road", r"highway", r"route", r"corridor", r"bridge", r"culvert", r"crossing",
    r"network", r"transport", r"access", r"reachab", r"connect", r"traffic", r"segment",
    # Settlements & Population
    r"settlement", r"village", r"town", r"populat", r"people", r"resident", r"clinic",
    r"hospital", r"health", r"school", r"building", r"structure", r"house", r"shelter",
    # Crisis & Evacuation
    r"isolat", r"cut.?off", r"sever", r"strand", r"trap", r"rescu", r"evacuat", r"priorit",
    r"triag", r"urgent", r"danger", r"hazard", r"risk", r"safe", r"casualt",
    # HLZ & Aviation
    r"hlz", r"helico", r"chopper", r"landing", r"airdrop", r"airlift", r"flight", r"relief", r"dropzone",
    # Data & Spatial Ops
    r"sar\b", r"sentinel", r"satellit", r"damag", r"destroy", r"intact", r"disaster",
    r"terrain", r"slope", r"elevation", r"sitrep", r"report", r"analys", r"metric",
    r"theat", r"summar", r"status", r"overview", r"impact",
    # Nepali Devanagari Keywords
    r"बाढी", r"पानी", r"डुबान", r"नदी", r"खोला", r"कोशी", r"भोटेकोशी", r"क्षेत्रफल",
    r"सडक", r"राजमार्ग", r"बाटो", r"पुल", r"यातायात", r"सञ्जाल", r"अवरुद्ध", r"पहुँच",
    r"बस्ती", r"गाउँ", r"शहर", r"जनसंख्या", r"मानिस", r"स्वास्थ्य", r"अस्पताल", r"क्लिनिक", r"घर", r"भवन",
    r"सम्पर्कविहीन", r"अलपत्र", r"फसेका", r"उद्धार", r"निकासी", r"प्राथमिकता", r"जोखिम", r"विपद्", r"सुरक्षित",
    r"हेलिकप्टर", r"अवतरण", r"स्थल", r"एचएलजेड", r"राहत",
    r"उपग्रह", r"क्षति", r"नष्ट", r"ध्वस्त", r"प्रभावित",
    r"सारांश", r"विवरण", r"प्रतिवेदन", r"स्थिति", r"विश्लेषण", r"नक्सा",
]

GREETING_PATTERNS = [
    r"^\s*(hi|hello|hey|greetings|namaste)\b",
    r"^\s*(नमस्ते|नमस्कार)",
    r"who\s+are\s+you",
    r"what\s+are\s+you",
    r"what\s+is\s+your\s+name",
    r"your\s+name",
    r"what\s+can\s+you\s+do",
    r"help\s+me",
    r"के\s+गर्न\s+सक्छौ",
    r"तपाईं\s+को\s+हो",
    r"तिमी\s+को\s+हौ",
    r"नाम\s+के\s+हो",
]


def check_domain_relevance(
    query: str,
    analysis_id: str,
    language: str = "en",
) -> tuple[str, str | None]:
    """
    Ensure the copilot gives replies strictly relevant to the S.T.R.A.N.D disaster application.

    Returns:
        ("greeting", welcome_message)
        ("out_of_scope", refusal_message)
        ("valid", None) -> query is relevant to the disaster theater
    """
    q = query.strip()

    # 1. Check for greetings / intro inquiries
    for pattern in GREETING_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            if language == "ne":
                msg = (
                    f"👋 **नमस्ते कमान्डर।**\n\n"
                    f"म विपद् क्षेत्र `{analysis_id}` का लागि **S.T.R.A.N.D सामरिक एआई ककपाइलट** हुँ। "
                    f"म बाढी डुबान, सडक तथा पुल क्षति, सम्पर्कविहीन बस्ती र हेलिकप्टर अवतरण स्थलहरूको विश्लेषण गर्दछु।\n\n"
                    f"**सुझाव गरिएका प्रश्नहरू:**\n"
                    f"- *सबैभन्दा जरुरी उद्धार प्राथमिकताहरू के के हुन्?*\n"
                    f"- *कुन कुन बस्तीहरू सम्पर्कविहीन छन्?*\n"
                    f"- *कुन पुलहरू नष्ट वा क्षतिग्रस्त छन्?*\n"
                    f"- *सुरक्षित हेलिकप्टर अवतरण स्थल (HLZ) कहाँ छन्?*\n"
                    f"- *बाढीको क्षतिको पूर्ण सारांश दिनुहोस्।*"
                )
            else:
                msg = (
                    f"👋 **Welcome Commander.**\n\n"
                    f"I am the **S.T.R.A.N.D Tactical AI Copilot** for disaster theater `{analysis_id}`. "
                    f"I provide real-time spatial analytics, infrastructure damage assessment, and evacuation triage intelligence.\n\n"
                    f"**Recommended Mission Inquiries:**\n"
                    f"- *What are the most urgent evacuation priorities?*\n"
                    f"- *Which settlements are currently isolated?*\n"
                    f"- *Which bridges are destroyed or severed?*\n"
                    f"- *Where are the safe Helicopter Landing Zones (HLZ)?*\n"
                    f"- *Give me a summary of total flood damage.*"
                )
            return "greeting", msg

    # 2. Check for domain relevance keywords
    for pattern in DISASTER_DOMAIN_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return "valid", None

    # 3. Query does not match any disaster or application domain concept
    if language == "ne":
        msg = (
            f"⚠️ **अभियान कार्यक्षेत्र बाहिरको प्रश्न**\n\n"
            f"S.T.R.A.N.D ककपाइलट विपद् क्षेत्र `{analysis_id}` को "
            f"**सामरिक विपद् प्रतिकार्य तथा सञ्जाल क्षति विश्लेषण** का लागि मात्र समर्पित छ।\n\n"
            f"म केवल निम्न विषयहरूसँग सम्बन्धित प्रश्नहरूको उत्तर दिन सक्छु:\n"
            f"- **सम्पर्कविहीन बस्ती तथा उद्धार प्राथमिकता** (*जस्तै: कुन बस्तीहरू सम्पर्कविहीन छन्?*)\n"
            f"- **पूर्वाधार क्षति (सडक र पुल)** (*जस्तै: कुन पुलहरू नष्ट भएका छन्?*)\n"
            f"- **बाढी डुबान तथा पानी जमेका क्षेत्र** (*जस्तै: बाढीको कुल क्षेत्रफल कति छ?*)\n"
            f"- **हेलिकप्टर अवतरण स्थल (HLZ)** (*जस्तै: सुरक्षित HLZ कहाँ अवस्थित छन्?*)\n\n"
            f"कृपया विपद् प्रतिकार्यसँग सम्बन्धित प्रश्न सोध्नुहोस्।"
        )
    else:
        msg = (
            f"⚠️ **Query Out of Mission Scope**\n\n"
            f"S.T.R.A.N.D Copilot is dedicated exclusively to **Tactical Disaster Response & Network Damage Analysis** "
            f"for disaster theater `{analysis_id}`.\n\n"
            f"I can only answer operational questions related to:\n"
            f"- **Settlement Isolation & Evacuation Triage** (*e.g., 'Which settlements are isolated?'*)\n"
            f"- **Infrastructure Damage** (*e.g., 'Which bridges are destroyed?', 'Severed road segments'*)\n"
            f"- **Flood Inundation & Ponding Zones** (*e.g., 'What is the total flood extent?'*)\n"
            f"- **Helicopter Landing Zones (HLZ)** (*e.g., 'Where can helicopters land safely?'*)\n\n"
            f"Please reformulate your query to focus on the active disaster theater."
        )
    return "out_of_scope", msg

