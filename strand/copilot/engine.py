"""
S.T.R.A.N.D — Bilingual NL-to-SQL Copilot Engine

Converts natural-language questions (English/Nepali) into SQL queries
against the DuckDB spatial database, executes them, and returns
grounded responses with mandatory SQL citations.

Design:
- Uses Google Gemini as the LLM backend
- System prompt contains the full database schema
- Every response MUST cite the executed SQL query
- Read-only database connection prevents data modification
- Hallucination detection via result cross-validation
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from strand.config import get_settings
from strand.copilot.guardrails import (
    GuardrailViolation,
    sanitize_query,
    validate_response,
    validate_sql_output,
)
from strand.db.connection import get_readonly_db

logger = logging.getLogger(__name__)


# System prompt containing the full schema for SQL generation
SYSTEM_PROMPT = """You are S.T.R.A.N.D Copilot, a bilingual (English/Nepali) disaster analyst assistant.

Your role is to answer questions about flood damage analysis data by generating SQL queries against a DuckDB Spatial database.

## CRITICAL RULES:
1. ONLY generate SELECT queries. NEVER generate INSERT, UPDATE, DELETE, or any data modification.
2. ALWAYS cite the SQL query you used in your response.
3. If the data doesn't contain the answer, say "No data available" — NEVER make up numbers.
4. Round decimal values to 2 decimal places.
5. Use km² for areas, km for distances, meters for short distances.
6. If asked in Nepali, respond in Nepali (Devanagari script).

## DATABASE SCHEMA:

### analyses
- id (VARCHAR PK), disaster_date (DATE), flood_area_km2 (DOUBLE), status (VARCHAR)
- roads_total_km, roads_severed_km, roads_partial_km (DOUBLE)
- bridges_total, bridges_destroyed, bridges_damaged (INTEGER)
- buildings_total, buildings_submerged, buildings_contact (INTEGER)
- settlements_total, settlements_isolated, settlements_degraded (INTEGER)
- hlz_count, ponding_count (INTEGER)

### flood_polygons
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- area_m2 (DOUBLE), confidence (DOUBLE), detection_method (VARCHAR)

### road_segments
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- highway_type (VARCHAR), name (VARCHAR), length_m (DOUBLE)
- damage_class (VARCHAR: 'intact', 'partially_flooded', 'severed')
- flood_intersection_ratio (DOUBLE)

### bridges
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- name (VARCHAR), damage_class (VARCHAR: 'intact', 'damaged', 'destroyed')
- buffer_flood_ratio (DOUBLE)

### buildings
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- building_type (VARCHAR), damage_class (VARCHAR: 'safe', 'flood_contact', 'submerged')

### settlements
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- name (VARCHAR), place_type (VARCHAR), estimated_population (INTEGER)
- isolation_status (VARCHAR: 'isolated', 'degraded', 'connected')
- urgency_score (DOUBLE), has_clinic (BOOLEAN)
- pre_disaster_hub_dist_m (DOUBLE), post_disaster_hub_dist_m (DOUBLE)

### hlz_sites
- id (VARCHAR PK), analysis_id (VARCHAR), centroid_wkt (VARCHAR)
- area_m2 (DOUBLE), avg_slope_deg (DOUBLE), elevation_m (DOUBLE)
- dist_to_settlement_m (DOUBLE), surface_estimate (VARCHAR)

### ponding_zones
- id (VARCHAR PK), analysis_id (VARCHAR), geom_wkt (VARCHAR)
- area_m2 (DOUBLE), estimated_volume_m3 (DOUBLE), risk_level (VARCHAR)

## RESPONSE FORMAT:
Provide a clear, concise answer. Include the SQL query used in a code block.
For Nepali queries, respond in Devanagari script but keep SQL in English.
"""


class CopilotEngine:
    """
    Bilingual NL-to-SQL copilot engine.

    Handles query sanitization, SQL generation via LLM,
    execution against read-only DuckDB, and response formatting.
    """

    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        settings = get_settings()
        self._api_key = settings.gemini.api_key
        self._model_name = settings.gemini.model

    async def answer(
        self,
        query: str,
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Process a natural language query and return a grounded response.

        Pipeline:
        1. Sanitize input (guardrails)
        2. Generate SQL via LLM
        3. Validate SQL (read-only check)
        4. Execute on DuckDB (read-only connection)
        5. Format response with citation
        6. Validate response (hallucination check)

        Args:
            query: Natural language question.
            language: 'en' for English, 'ne' for Nepali.

        Returns:
            Dict with answer, citation, and metadata.
        """
        logger.info("Copilot query [%s]: %s", language, query[:100])

        # Step 1: Sanitize
        try:
            clean_query = sanitize_query(query)
        except GuardrailViolation as e:
            return self._error_response(str(e), language)

        # Step 2: Generate SQL
        try:
            sql = await self._generate_sql(clean_query, language)
        except Exception as e:
            logger.error("SQL generation failed: %s", e)
            return self._error_response(
                "I couldn't understand that question. Please rephrase." if language == "en"
                else "मैले त्यो प्रश्न बुझ्न सकिनँ। कृपया पुन: भन्नुहोस्।",
                language,
            )

        # Step 3: Validate SQL
        if not validate_sql_output(sql):
            logger.warning("Invalid SQL generated: %s", sql[:200])
            return self._error_response(
                "I can only answer questions about the flood analysis data." if language == "en"
                else "म बाढी विश्लेषण डेटाको बारेमा मात्र प्रश्नहरूको उत्तर दिन सक्छु।",
                language,
            )

        # Step 4: Execute SQL
        try:
            result = self._execute_sql(sql)
        except Exception as e:
            logger.error("SQL execution failed: %s — SQL: %s", e, sql[:200])
            return self._error_response(
                f"Query failed: {e}" if language == "en"
                else f"क्वेरी असफल भयो: {e}",
                language,
            )

        # Step 5: Format response
        try:
            answer_text = await self._format_response(
                clean_query, sql, result, language
            )
        except Exception as e:
            logger.error("Response formatting failed: %s", e)
            answer_text = self._format_raw_result(result, language)

        # Step 6: Validate response
        is_valid, reason = validate_response(answer_text, result)
        if not is_valid:
            logger.warning("Hallucination detected: %s", reason)
            answer_text = self._format_raw_result(result, language)

        # Log query
        self._log_query(query, language, sql, answer_text, is_valid)

        return {
            "answer": answer_text,
            "language": language,
            "citation": {
                "sql": sql,
                "raw_result": result,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
            "hallucination_check": is_valid,
            "confidence": "high" if is_valid else "low",
        }

    async def _generate_sql(self, query: str, language: str) -> str:
        """Generate SQL from natural language using Gemini."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model_name)

            prompt = (
                f"{SYSTEM_PROMPT}\n\n"
                f"Analysis ID to use in WHERE clauses: '{self.analysis_id}'\n\n"
                f"User query ({language}): {query}\n\n"
                f"Generate ONLY the SQL query (no explanation). "
                f"Always include WHERE analysis_id = '{self.analysis_id}'."
            )

            response = model.generate_content(prompt)
            sql = response.text.strip()

            # Extract SQL from code block if present
            if "```sql" in sql:
                sql = sql.split("```sql")[1].split("```")[0].strip()
            elif "```" in sql:
                sql = sql.split("```")[1].split("```")[0].strip()

            return sql

        except ImportError:
            # Fallback: pattern-matching SQL generation
            return self._pattern_match_sql(query)

    async def _format_response(
        self, query: str, sql: str, result: dict, language: str
    ) -> str:
        """Format the SQL result into a natural language response."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model_name)

            lang_instruction = (
                "Respond in English." if language == "en"
                else "Respond in Nepali (Devanagari script)."
            )

            prompt = (
                f"Based on this SQL query and result, provide a clear, concise answer.\n"
                f"{lang_instruction}\n"
                f"Include the SQL in a code block for citation.\n"
                f"ONLY use numbers from the result — do NOT make up data.\n\n"
                f"Query: {query}\n"
                f"SQL: {sql}\n"
                f"Result: {json.dumps(result, default=str)}\n"
            )

            response = model.generate_content(prompt)
            return response.text.strip()

        except ImportError:
            return self._format_raw_result(result, language)

    def _execute_sql(self, sql: str) -> dict[str, Any]:
        """Execute SQL on read-only DuckDB connection."""
        conn = get_readonly_db()
        try:
            result = conn.execute(sql).fetchall()
            columns = [desc[0] for desc in conn.description]

            if not result:
                return {"message": "No data found", "rows": 0}

            if len(result) == 1:
                return dict(zip(columns, result[0]))
            else:
                return {
                    "columns": columns,
                    "rows": [dict(zip(columns, row)) for row in result[:20]],
                    "total_rows": len(result),
                }
        finally:
            conn.close()

    def _pattern_match_sql(self, query: str) -> str:
        """Fallback SQL generation using pattern matching (no LLM needed)."""
        q = query.lower()
        aid = self.analysis_id

        if any(w in q for w in ["flood", "area", "extent", "बाढी"]):
            return f"SELECT flood_area_km2 FROM analyses WHERE id = '{aid}'"

        if any(w in q for w in ["road", "severed", "sडक"]):
            return (
                f"SELECT roads_total_km, roads_severed_km, roads_partial_km "
                f"FROM analyses WHERE id = '{aid}'"
            )

        if any(w in q for w in ["bridge", "पुल"]):
            return (
                f"SELECT bridges_total, bridges_destroyed, bridges_damaged "
                f"FROM analyses WHERE id = '{aid}'"
            )

        if any(w in q for w in ["isolated", "cut off", "isolation", "अलग"]):
            return (
                f"SELECT name, isolation_status, urgency_score, estimated_population "
                f"FROM settlements WHERE analysis_id = '{aid}' "
                f"AND isolation_status != 'connected' "
                f"ORDER BY urgency_score DESC LIMIT 10"
            )

        if any(w in q for w in ["urgent", "priority", "triage", "प्राथमिकता"]):
            return (
                f"SELECT name, urgency_score, isolation_status, estimated_population "
                f"FROM settlements WHERE analysis_id = '{aid}' "
                f"ORDER BY urgency_score DESC LIMIT 10"
            )

        if any(w in q for w in ["hlz", "helicopter", "landing", "हेलिकप्टर"]):
            return (
                f"SELECT id, avg_slope_deg, area_m2, elevation_m, dist_to_settlement_m "
                f"FROM hlz_sites WHERE analysis_id = '{aid}' "
                f"ORDER BY dist_to_settlement_m ASC LIMIT 10"
            )

        if any(w in q for w in ["building", "house", "भवन"]):
            return (
                f"SELECT buildings_total, buildings_submerged, buildings_contact "
                f"FROM analyses WHERE id = '{aid}'"
            )

        if any(w in q for w in ["summary", "overview", "सारांश"]):
            return (
                f"SELECT flood_area_km2, roads_severed_km, bridges_destroyed, "
                f"buildings_submerged, settlements_isolated "
                f"FROM analyses WHERE id = '{aid}'"
            )

        # Default: return analysis summary
        return f"SELECT * FROM analyses WHERE id = '{aid}'"

    def _format_raw_result(self, result: dict, language: str) -> str:
        """Format raw SQL result as a simple text response."""
        if "message" in result and result.get("rows") == 0:
            return (
                "No data found for this query."
                if language == "en"
                else "यस क्वेरीको लागि कुनै डेटा फेला परेन।"
            )

        lines = []
        for key, value in result.items():
            if key in ("columns", "rows", "total_rows"):
                continue
            if isinstance(value, float):
                lines.append(f"- **{key}**: {value:.2f}")
            else:
                lines.append(f"- **{key}**: {value}")

        if "rows" in result:
            for row in result["rows"][:5]:
                row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                lines.append(f"- {row_str}")

        return "\n".join(lines) if lines else str(result)

    def _error_response(self, message: str, language: str) -> dict[str, Any]:
        """Create an error response dict."""
        return {
            "answer": message,
            "language": language,
            "citation": None,
            "hallucination_check": True,
            "confidence": "low",
        }

    def _log_query(
        self, query: str, language: str, sql: str, response: str, valid: bool
    ) -> None:
        """Log the copilot query to the database."""
        import uuid as _uuid
        try:
            from strand.db.connection import get_db
            db = get_db()
            db.execute(
                """
                INSERT INTO copilot_queries
                    (id, analysis_id, user_query, language, generated_sql,
                     response_text, hallucination_check)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(_uuid.uuid4()), self.analysis_id,
                    query, language, sql, response[:1000], valid,
                ],
            )
        except Exception as e:
            logger.warning("Failed to log copilot query: %s", e)
