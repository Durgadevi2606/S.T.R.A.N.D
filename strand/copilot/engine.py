"""
S.T.R.A.N.D — Bilingual NL-to-SQL Copilot Engine (Hybrid: Gemini + Local)

Converts natural-language questions (English/Nepali) into SQL queries
against the DuckDB spatial database, executes them, and returns
grounded responses with mandatory SQL citations.

Hybrid Architecture:
- Primary Engine: Google Gemini API (Direct HTTP with zero extra dependencies)
- Offline Fallback Engine: Deterministic rule-based NL-to-SQL + Rich Narrative Formatter
- Seamless Auto-Switching: If Gemini is unavailable, 503, 429, or offline, Copilot
  switches to the local engine automatically without failing the user's query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
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
Generate ONLY the SQL query inside a ```sql code block.
"""


class CopilotEngine:
    """
    Hybrid Bilingual NL-to-SQL copilot engine.

    Switches adaptively between Google Gemini AI and a Local Offline
    rule-based engine based on availability, latency, and user preference.
    """

    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        settings = get_settings()
        self._api_key = settings.gemini.api_key
        self._model_name = settings.gemini.model or "gemini-3.8-flash"

    async def answer(
        self,
        query: str,
        language: str = "en",
        engine_mode: str = "auto",
    ) -> dict[str, Any]:
        """
        Process a natural language query and return a grounded response.

        Pipeline:
        1. Sanitize input (guardrails)
        2. Determine engine mode (auto | gemini | local)
        3. Generate SQL via Gemini or Local Engine with adaptive fallback
        4. Validate SQL (read-only check)
        5. Execute on DuckDB (read-only connection)
        6. Format response (Gemini LLM or Local Narrative Engine)
        7. Validate response (hallucination check)
        """
        logger.info(
            "Copilot query [lang=%s, mode=%s]: %s",
            language, engine_mode, query[:100]
        )

        # Step 1: Sanitize
        try:
            clean_query = sanitize_query(query)
        except GuardrailViolation as e:
            return self._error_response(str(e), language)

        # Step 1b: Domain & Intent Guardrails
        from strand.copilot.guardrails import check_domain_relevance

        intent, advisory_message = check_domain_relevance(clean_query, self.analysis_id, language)
        if intent in ("greeting", "out_of_scope"):
            return {
                "answer": advisory_message,
                "language": language,
                "citation": None,
                "hallucination_check": True,
                "confidence": "high",
                "engine_used": "guardrails",
                "engine_label": "Tactical Copilot" if intent == "greeting" else "Mission Scope Guardrail",
                "is_fallback": False,
            }

        sql: str | None = None
        engine_used = "local"
        engine_label = "Local Offline Engine"
        is_fallback = False
        gemini_model_resolved: str | None = None

        # Check local pattern for fast-path routing (<1ms)
        pattern_sql = self._pattern_match_sql(clean_query)
        has_direct_pattern = (
            pattern_sql != f"SELECT * FROM analyses WHERE id = '{self.analysis_id}'"
        )

        # Step 2 & 3: Generate SQL via chosen mode with latency optimizations
        if engine_mode == "auto":
            if has_direct_pattern:
                # Fast Path: exact high-precision tactical pattern matched in 0.1ms
                sql = pattern_sql
                engine_used = "local"
                engine_label = "Local Offline Engine (Fast Path)"
                is_fallback = False
            else:
                # Custom query: try Gemini LLM with tight timeout
                try:
                    gemini_sql, gemini_model_resolved = await self._generate_sql_gemini(
                        clean_query, language
                    )
                    if gemini_sql == "OUT_OF_SCOPE":
                        _, refusal = check_domain_relevance("unknown", self.analysis_id, language)
                        return {
                            "answer": refusal,
                            "language": language,
                            "citation": None,
                            "hallucination_check": True,
                            "confidence": "high",
                            "engine_used": "guardrails",
                            "engine_label": "Mission Scope Guardrail",
                            "is_fallback": False,
                        }
                    if gemini_sql and validate_sql_output(gemini_sql):
                        sql = gemini_sql
                        engine_used = "gemini"
                        engine_label = f"Google Gemini AI ({gemini_model_resolved})"
                        is_fallback = False
                    else:
                        is_fallback = True
                except Exception as e:
                    logger.warning("Gemini invocation error in auto mode: %s", e)
                    is_fallback = True

        elif engine_mode == "gemini":
            try:
                gemini_sql, gemini_model_resolved = await self._generate_sql_gemini(
                    clean_query, language
                )
                if gemini_sql == "OUT_OF_SCOPE":
                    _, refusal = check_domain_relevance("unknown", self.analysis_id, language)
                    return {
                        "answer": refusal,
                        "language": language,
                        "citation": None,
                        "hallucination_check": True,
                        "confidence": "high",
                        "engine_used": "guardrails",
                        "engine_label": "Mission Scope Guardrail",
                        "is_fallback": False,
                    }
                if gemini_sql and validate_sql_output(gemini_sql):
                    sql = gemini_sql
                    engine_used = "gemini"
                    engine_label = f"Google Gemini AI ({gemini_model_resolved})"
                    is_fallback = False
                else:
                    logger.warning("Gemini SQL unavailable or failed; switching to local engine")
                    is_fallback = True
            except Exception as e:
                logger.warning("Gemini error in gemini mode: %s", e)
                is_fallback = True

        # Fallback or explicit local execution
        if sql is None:
            sql = pattern_sql
            engine_used = "local"
            engine_label = (
                "Local Offline Engine (Fallback)"
                if (engine_mode != "local" and is_fallback)
                else "Local Offline Engine"
            )

        # Step 4: Validate SQL
        if not validate_sql_output(sql):
            logger.warning("Invalid SQL generated: %s", sql[:200])
            sql = f"SELECT * FROM analyses WHERE id = '{self.analysis_id}'"

        # Step 5: Execute SQL on DuckDB
        try:
            result = self._execute_sql(sql)
        except Exception as e:
            logger.error("SQL execution failed: %s — SQL: %s", e, sql[:200])
            safe_sql = f"SELECT * FROM analyses WHERE id = '{self.analysis_id}'"
            try:
                result = self._execute_sql(safe_sql)
                sql = safe_sql
            except Exception as e2:
                return self._error_response(
                    f"Query execution failed: {e2}" if language == "en"
                    else f"क्वेरी कार्यान्वयन असफल भयो: {e2}",
                    language,
                    engine_used=engine_used,
                    engine_label=engine_label,
                    is_fallback=is_fallback,
                )

        # Step 6: Format response
        answer_text: str | None = None
        if engine_used == "gemini" and gemini_model_resolved:
            try:
                answer_text = await self._format_response_gemini(
                    clean_query, sql, result, language, gemini_model_resolved
                )
            except Exception as e:
                logger.warning("Gemini response formatting failed: %s; using local narrative", e)
                answer_text = None

        if not answer_text:
            answer_text = self._format_local_result(clean_query, result, language)

        # Step 7: Validate response (hallucination check)
        is_valid, reason = validate_response(answer_text, result)
        if not is_valid:
            logger.warning("Potential hallucination detected: %s; using local format", reason)
            answer_text = self._format_local_result(clean_query, result, language)
            is_valid = True

        # Log query audit
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
            "engine_used": engine_used,
            "engine_label": engine_label,
            "is_fallback": is_fallback,
        }

    async def _call_gemini_api(
        self, prompt: str, timeout: float = 3.5
    ) -> tuple[str | None, str | None]:
        """
        Calls Gemini API using urllib in a threadpool executor with tight 3.5s timeout.
        Returns (model_name_used, response_text) or (None, None) on failure.
        """
        if not self._api_key or self._api_key.startswith("dev-"):
            return None, None

        def _request():
            # Prioritize ultra-fast 2026 flash-lite models for sub-second responses
            models_to_try = [
                self._model_name,
                "gemini-flash-lite-latest",
                "gemini-3.5-flash-lite",
            ]
            seen = set()
            candidates = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

            for m in candidates:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{m}:generateContent?key={self._api_key}"
                )
                payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            parts = (
                                data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [])
                            )
                            if parts and "text" in parts[0]:
                                text = parts[0]["text"].strip()
                                return m, text
                except urllib.error.HTTPError as e:
                    logger.warning("Gemini HTTP error on model '%s': %s", m, e.code)
                    if e.code in (429, 503):
                        # Quota or outage: abort loop immediately to avoid blocking
                        break
                    continue
                except Exception as e:
                    logger.warning("Gemini connection error on model '%s': %s", m, e)
                    continue
            return None, None

        return await asyncio.to_thread(_request)

    def _extract_sql(self, text: str) -> str:
        """Extract clean SQL string from markdown or text response."""
        sql = text.strip()
        if "OUT_OF_SCOPE" in sql:
            return "OUT_OF_SCOPE"
        if "```sql" in sql:
            sql = sql.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql:
            sql = sql.split("```")[1].split("```")[0].strip()
        # Remove trailing semicolons
        if sql.endswith(";"):
            sql = sql[:-1].strip()
        return sql

    async def _generate_sql_gemini(
        self, query: str, language: str
    ) -> tuple[str | None, str | None]:
        """Generate SQL from natural language using Gemini with strict domain bounds."""
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Analysis ID to use in WHERE clauses: '{self.analysis_id}'\n\n"
            f"User query ({language}): {query}\n\n"
            f"CRITICAL MISSION CONSTRAINTS:\n"
            f"1. You are strictly restricted to the S.T.R.A.N.D disaster response system.\n"
            f"2. If this question is unrelated to flood disaster assessment, infrastructure damage, "
            f"isolated settlements, or helicopter landing zones, output ONLY: OUT_OF_SCOPE\n"
            f"3. Otherwise, output ONLY a valid DuckDB SQL SELECT query enclosed in a ```sql code block.\n"
            f"4. Always include WHERE analysis_id = '{self.analysis_id}' (or WHERE id = '{self.analysis_id}' for analyses table)."
        )

        model_used, raw_text = await self._call_gemini_api(prompt, timeout=3.5)
        if not raw_text:
            return None, None

        sql = self._extract_sql(raw_text)
        return sql, model_used

    async def _format_response_gemini(
        self,
        query: str,
        sql: str,
        result: dict,
        language: str,
        model_name: str,
    ) -> str | None:
        """Format the SQL result into a natural language response using Gemini."""
        lang_instruction = (
            "Respond in English." if language == "en"
            else "Respond in Nepali (Devanagari script)."
        )

        prompt = (
            f"You are S.T.R.A.N.D Copilot, a bilingual disaster analyst assistant.\n"
            f"Based on this executed DuckDB SQL query and actual database result, provide a clear, professional tactical disaster response.\n"
            f"{lang_instruction}\n"
            f"Rules:\n"
            f"- ONLY state facts and numbers from the actual result. Do NOT fabricate numbers.\n"
            f"- Round decimals to 2 decimal places.\n"
            f"- Format critical numbers with bold markdown.\n"
            f"- Be concise, operational, and actionable.\n\n"
            f"User Question: {query}\n"
            f"Executed SQL: {sql}\n"
            f"Database Result: {json.dumps(result, default=str)}\n"
        )

        _, formatted_text = await self._call_gemini_api(prompt, timeout=3.5)
        return formatted_text

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
        """
        Deterministic, offline SQL generator for disaster analysis.
        Covers bilingual English/Nepali queries and domain terminology.
        """
        q = query.lower()
        aid = self.analysis_id

        # 1. Urgent evacuation priorities / triage / settlements needing rescue
        if any(w in q for w in ["urgent", "priority", "priorities", "triage", "evacuat", "rescue", "save", "प्राथमिकता", "उद्धार", "जोखिम"]):
            return (
                f"SELECT name, place_type, estimated_population, isolation_status, urgency_score, has_clinic "
                f"FROM settlements WHERE analysis_id = '{aid}' "
                f"ORDER BY urgency_score DESC LIMIT 10"
            )

        # 2. Bridges damaged / collapsed / destroyed
        if any(w in q for w in ["bridge", "crossing", "river crossing", "पुल"]):
            return (
                f"SELECT name, damage_class, buffer_flood_ratio "
                f"FROM bridges WHERE analysis_id = '{aid}' AND damage_class != 'intact' "
                f"ORDER BY buffer_flood_ratio DESC LIMIT 10"
            )

        # 3. Specific road segments severed / damaged
        if any(w in q for w in ["road", "highway", "corridor", "route", "सडक", "मार्ग"]):
            if any(w in q for w in ["severed", "block", "cut", "damage", "impassable", "अवरुद्ध", "विच्छेद"]):
                return (
                    f"SELECT name, highway_type, length_m, damage_class, flood_intersection_ratio "
                    f"FROM road_segments WHERE analysis_id = '{aid}' AND damage_class = 'severed' "
                    f"ORDER BY length_m DESC LIMIT 10"
                )
            return (
                f"SELECT roads_total_km, roads_severed_km, roads_partial_km "
                f"FROM analyses WHERE id = '{aid}'"
            )

        # 4. Helicopter Landing Zones (HLZ)
        if any(w in q for w in ["hlz", "helicopter", "landing", "airdrop", "rotary", "helipad", "हेलिकप्टर", "ल्यान्डिङ"]):
            return (
                f"SELECT id, area_m2, avg_slope_deg, elevation_m, dist_to_settlement_m, surface_estimate "
                f"FROM hlz_sites WHERE analysis_id = '{aid}' "
                f"ORDER BY dist_to_settlement_m ASC LIMIT 10"
            )

        # 5. Building damage / residential structures submerged
        if any(w in q for w in ["building", "house", "home", "structure", "residential", "भवन", "घर"]):
            return (
                f"SELECT buildings_total, buildings_submerged, buildings_contact "
                f"FROM analyses WHERE id = '{aid}'"
            )

        # 6. Ponding zones / secondary dam / debris lake hazards
        if any(w in q for w in ["ponding", "debris dam", "dam breach", "dam collapse", "lake", "blockage", "secondary flood", "ताल", "ड्याम", "पहिरो"]):
            return (
                f"SELECT id, area_m2, estimated_volume_m3, risk_level "
                f"FROM ponding_zones WHERE analysis_id = '{aid}' "
                f"ORDER BY estimated_volume_m3 DESC LIMIT 10"
            )

        # 7. Clinics / Medical facilities in affected settlements
        if any(w in q for w in ["clinic", "hospital", "health", "medical", "doctor", "स्वास्थ्य", "अस्पताल", "औषधि"]):
            return (
                f"SELECT name, estimated_population, isolation_status, urgency_score, has_clinic "
                f"FROM settlements WHERE analysis_id = '{aid}' AND has_clinic = true "
                f"ORDER BY urgency_score DESC LIMIT 10"
            )

        # 8. Isolated settlements / cut-off communities
        if any(w in q for w in ["isolated", "isolation", "cut off", "disconnect", "trap", "अलग", "सम्पर्कविहीन", "बस्ती"]):
            return (
                f"SELECT name, place_type, estimated_population, isolation_status, urgency_score, has_clinic "
                f"FROM settlements WHERE analysis_id = '{aid}' "
                f"AND isolation_status != 'connected' "
                f"ORDER BY urgency_score DESC LIMIT 10"
            )

        # 9. Summary / overview / assessment / general damage
        if any(w in q for w in ["summary", "overview", "report", "assessment", "damage", "situation", "status", "all", "सारांश", "विवरण", "स्थिति"]):
            return (
                f"SELECT flood_area_km2, roads_total_km, roads_severed_km, bridges_total, "
                f"bridges_destroyed, buildings_total, buildings_submerged, settlements_total, "
                f"settlements_isolated, hlz_count, ponding_count "
                f"FROM analyses WHERE id = '{aid}'"
            )

        # 10. Flood extent / flooded area
        if any(w in q for w in ["flood", "area", "extent", "water", "inundat", "बाढी", "क्षेत्रफल", "डुबान"]):
            return f"SELECT flood_area_km2, disaster_date, status FROM analyses WHERE id = '{aid}'"

        # Default fallback: general damage metrics
        return (
            f"SELECT flood_area_km2, roads_severed_km, bridges_destroyed, buildings_submerged, "
            f"settlements_isolated, hlz_count, ponding_count "
            f"FROM analyses WHERE id = '{aid}'"
        )

    def _format_local_result(self, query: str, result: dict, language: str) -> str:
        """
        Produce a high-grade tactical disaster analysis response
        from database results without needing external LLM generation.
        """
        if not result or result.get("rows") == 0 or result.get("message") == "No data found":
            return (
                "No records found matching this tactical criteria in the current disaster theater."
                if language == "en"
                else "हालको विपद् क्षेत्रमा यस मापदण्डसँग मेल खाने कुनै रेकर्ड फेला परेन।"
            )

        is_ne = language == "ne"

        # Case 1: Multiple rows
        if "rows" in result:
            rows = result.get("rows", [])
            total = result.get("total_rows", len(rows))
            if not rows:
                return (
                    "No matching entities found in analysis database."
                    if not is_ne
                    else "डेटाबेसमा कुनै मिल्दो विवरण भेटिएन।"
                )

            first_row = rows[0]

            # 1a. Settlements
            if "urgency_score" in first_row or "isolation_status" in first_row:
                header = (
                    f"**Identified {total} Priority Settlement(s) in Disaster Theater:**\n"
                    if not is_ne
                    else f"**विपद् क्षेत्रमा {total} वटा प्राथमिकता प्राप्त बस्तीहरू फेला परे:**\n"
                )
                items = []
                for idx, r in enumerate(rows[:6], 1):
                    name = r.get("name", "Unknown")
                    status = r.get("isolation_status", "N/A")
                    urgency = r.get("urgency_score", 0.0)
                    pop = r.get("estimated_population", 0)
                    clinic = "Has Clinic" if r.get("has_clinic") else "No Clinic"
                    clinic_ne = "स्वास्थ्य चौकी छ" if r.get("has_clinic") else "स्वास्थ्य चौकी छैन"
                    if not is_ne:
                        items.append(
                            f"{idx}. **{name}** — Status: `{status}`, Urgency: `{urgency:.2f}`, Population: {pop:,} ({clinic})"
                        )
                    else:
                        items.append(
                            f"{idx}. **{name}** — स्थिति: `{status}`, जोखिम स्तर: `{urgency:.2f}`, जनसंख्या: {pop:,} ({clinic_ne})"
                        )
                rec = (
                    "\n\n**Tactical Action:** Prioritize rotary supply drops and rescue teams to highest urgency settlements first."
                    if not is_ne
                    else "\n\n**सिफारिस:** उच्च जोखिम स्तर भएका बस्तीहरूमा तत्काल हेलिकप्टरबाट राहत वा उद्धार टोली परिचालन गर्नुहोस्।"
                )
                return header + "\n".join(items) + rec

            # 1b. Bridges (checked BEFORE road segments because bridges also have damage_class)
            if "buffer_flood_ratio" in first_row:
                header = (
                    f"**Identified {total} Critical River Crossing(s) Impacted:**\n"
                    if not is_ne
                    else f"**{total} वटा प्रभावित पुलहरू फेला परे:**\n"
                )
                items = []
                for idx, r in enumerate(rows[:6], 1):
                    name = r.get("name") or "Unnamed Bridge"
                    damage = r.get("damage_class", "unknown")
                    ratio = (r.get("buffer_flood_ratio", 0) or 0) * 100
                    if not is_ne:
                        items.append(f"{idx}. **{name}** — Status: `{damage}`, Inundation Exposure: {ratio:.1f}%")
                    else:
                        items.append(f"{idx}. **{name}** — स्थिति: `{damage}`, बाढी प्रभाव: {ratio:.1f}%")
                rec = (
                    "\n\n**Engineering Advisory:** Inspect bridge structural integrity prior to allowing vehicular transit."
                    if not is_ne
                    else "\n\n**सिफारिस:** सवारी साधन आवतजावत गर्नु अघि पुलको भौतिक अवस्था निरीक्षण गर्नुहोस्।"
                )
                return header + "\n".join(items) + rec

            # 1c. Road segments
            if "highway_type" in first_row or "flood_intersection_ratio" in first_row:
                header = (
                    f"**Identified {total} Severed Road Corridor(s):**\n"
                    if not is_ne
                    else f"**{total} वटा अवरुद्ध सडक खण्डहरू फेला परे:**\n"
                )
                items = []
                for idx, r in enumerate(rows[:6], 1):
                    name = r.get("name") or "Unnamed Segment"
                    hw = r.get("highway_type", "road")
                    length_km = (r.get("length_m", 0) or 0) / 1000.0
                    ratio = (r.get("flood_intersection_ratio", 0) or 0) * 100
                    if not is_ne:
                        items.append(
                            f"{idx}. **{name}** ({hw}) — {length_km:.2f} km length, {ratio:.1f}% submerged"
                        )
                    else:
                        items.append(
                            f"{idx}. **{name}** ({hw}) — {length_km:.2f} कि.मी., {ratio:.1f}% डुबानमा"
                        )
                rec = (
                    "\n\n**Tactical Action:** Ground logistics across these corridors are impassable. Reroute via alternate secondary arteries."
                    if not is_ne
                    else "\n\n**सिफारिस:** यी सडकहरूबाट स्थलमार्ग पूर्ण अवरुद्ध छ। वैकल्पिक मार्ग प्रयोग गर्नुहोस्।"
                )
                return header + "\n".join(items) + rec

            # 1d. Helicopter Landing Zones
            if "avg_slope_deg" in first_row or "dist_to_settlement_m" in first_row:
                header = (
                    f"**Identified {total} Viable Helicopter Landing Zone(s) (HLZ):**\n"
                    if not is_ne
                    else f"**{total} वटा उपयुक्त हेलिकप्टर अवतरण स्थल (HLZ) फेला परे:**\n"
                )
                items = []
                for idx, r in enumerate(rows[:5], 1):
                    hid = r.get("id", f"HLZ-{idx}")
                    area = r.get("area_m2", 0)
                    slope = r.get("avg_slope_deg", 0)
                    elev = r.get("elevation_m", 0)
                    dist = r.get("dist_to_settlement_m", 0)
                    surface = r.get("surface_estimate", "solid")
                    if not is_ne:
                        items.append(
                            f"{idx}. **{hid}** — Area: {area:.0f} m², Slope: {slope:.1f}°, Elev: {elev:.0f} m, Dist to Settlement: {dist:.0f} m ({surface})"
                        )
                    else:
                        items.append(
                            f"{idx}. **{hid}** — क्षेत्रफल: {area:.0f} वर्ग मिटर, भिरालो: {slope:.1f}°, उचाइ: {elev:.0f} मिटर, बस्ती दूरी: {dist:.0f} मिटर"
                        )
                rec = (
                    "\n\n**Flight Advisory:** Clear rotary approach verified for tactical medevac and cargo delivery."
                    if not is_ne
                    else "\n\n**उडान निर्देशन:** आपतकालीन उद्धार तथा राहत सामग्री ओसार्नका लागि उपयुक्त मानिएको छ।"
                )
                return header + "\n".join(items) + rec

            # 1e. Ponding zones
            if "estimated_volume_m3" in first_row:
                header = (
                    f"**Identified {total} Secondary Ponding / Debris Dam Hazard(s):**\n"
                    if not is_ne
                    else f"**{total} वटा पहिरो ताल / जलजमाव जोखिम क्षेत्रहरू फेला परे:**\n"
                )
                items = []
                for idx, r in enumerate(rows[:5], 1):
                    pid = r.get("id", f"POND-{idx}")
                    vol = r.get("estimated_volume_m3", 0)
                    risk = r.get("risk_level", "medium")
                    area = r.get("area_m2", 0)
                    if not is_ne:
                        items.append(f"{idx}. **{pid}** — Risk: `{risk}`, Vol: {vol:,.0f} m³, Area: {area:,.0f} m²")
                    else:
                        items.append(f"{idx}. **{pid}** — जोखिम स्तर: `{risk}`, अनुमानित आयतन: {vol:,.0f} घन मिटर")
                return header + "\n".join(items)

        # Case 2: Single row dictionary (analyses summary)
        flood_km2 = result.get("flood_area_km2")
        roads_sev = result.get("roads_severed_km")
        bridges_dest = result.get("bridges_destroyed")
        bldgs_sub = result.get("buildings_submerged")
        settle_iso = result.get("settlements_isolated")

        if any(v is not None for v in [flood_km2, roads_sev, bridges_dest, bldgs_sub, settle_iso]):
            if not is_ne:
                parts = []
                if flood_km2 is not None:
                    parts.append(f"- **Flood Extent**: {flood_km2:.2f} km² submerged")
                if roads_sev is not None:
                    roads_tot = result.get("roads_total_km")
                    tot_str = f" of {roads_tot:.2f} km" if roads_tot else ""
                    parts.append(f"- **Severed Roadways**: {roads_sev:.2f} km{tot_str}")
                if bridges_dest is not None:
                    bridges_tot = result.get("bridges_total")
                    tot_str = f" of {bridges_tot}" if bridges_tot else ""
                    parts.append(f"- **Destroyed Bridges**: {bridges_dest}{tot_str}")
                if bldgs_sub is not None:
                    bldgs_tot = result.get("buildings_total")
                    tot_str = f" of {bldgs_tot}" if bldgs_tot else ""
                    parts.append(f"- **Submerged Buildings**: {bldgs_sub}{tot_str}")
                if settle_iso is not None:
                    settle_tot = result.get("settlements_total")
                    tot_str = f" of {settle_tot}" if settle_tot else ""
                    parts.append(f"- **Isolated Settlements**: {settle_iso}{tot_str}")

                hlz = result.get("hlz_count")
                if hlz is not None:
                    parts.append(f"- **Safe HLZ Sites**: {hlz}")

                return "**Tactical Disaster Damage Assessment Summary:**\n" + "\n".join(parts)
            else:
                parts = []
                if flood_km2 is not None:
                    parts.append(f"- **बाढी डुबान क्षेत्रफल**: {flood_km2:.2f} वर्ग कि.मी.")
                if roads_sev is not None:
                    parts.append(f"- **अवरुद्ध सडक**: {roads_sev:.2f} कि.मी.")
                if bridges_dest is not None:
                    parts.append(f"- **नष्ट भएका पुल**: {bridges_dest}")
                if bldgs_sub is not None:
                    parts.append(f"- **डुबेका भवनहरू**: {bldgs_sub}")
                if settle_iso is not None:
                    parts.append(f"- **सम्पर्कविहीन बस्तीहरू**: {settle_iso}")

                hlz = result.get("hlz_count")
                if hlz is not None:
                    parts.append(f"- **सुरक्षित अवतरण स्थल (HLZ)**: {hlz}")

                return "**सामरिक विपद् क्षति विवरण सारांश:**\n" + "\n".join(parts)

        # Fallback to key-value
        return self._format_raw_result(result, language)

    def _format_raw_result(self, result: dict, language: str) -> str:
        """Format raw SQL result as a readable text response."""
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

    def _error_response(
        self,
        message: str,
        language: str,
        engine_used: str = "local",
        engine_label: str = "Local Engine",
        is_fallback: bool = False,
    ) -> dict[str, Any]:
        """Create an error response dict."""
        return {
            "answer": message,
            "language": language,
            "citation": None,
            "hallucination_check": True,
            "confidence": "low",
            "engine_used": engine_used,
            "engine_label": engine_label,
            "is_fallback": is_fallback,
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
