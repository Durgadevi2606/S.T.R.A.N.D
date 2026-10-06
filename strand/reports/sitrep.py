"""
S.T.R.A.N.D — PDF Situation Report (SitRep) Generator

Generates a formal A4 PDF report containing:
- Flood extent map with symbology
- Damage statistics tables
- Isolation triage list
- HLZ coordinates
- Mandatory legal attributions

Uses Jinja2 templates + WeasyPrint for HTML→PDF conversion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from strand.config import ALL_ATTRIBUTIONS, get_settings
from strand.db.spatial_queries import (
    compute_analysis_statistics,
    get_analysis_summary,
    get_analysis_warnings,
)

logger = logging.getLogger(__name__)


SITREP_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="UTF-8">
<title>S.T.R.A.N.D — Situation Report</title>
<style>
  @page { size: A4; margin: 2cm; }
  body { font-family: 'Inter', 'Noto Sans Devanagari', sans-serif; font-size: 10pt; color: #1a1a2e; line-height: 1.5; }
  h1 { color: #0d1117; font-size: 18pt; border-bottom: 3px solid #1f6feb; padding-bottom: 8px; }
  h2 { color: #1f6feb; font-size: 13pt; margin-top: 20px; border-bottom: 1px solid #30363d; padding-bottom: 4px; }
  h3 { color: #58a6ff; font-size: 11pt; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9pt; }
  th { background: #161b22; color: #c9d1d9; padding: 6px 8px; text-align: left; }
  td { padding: 5px 8px; border-bottom: 1px solid #30363d; }
  tr:nth-child(even) { background: #f6f8fa; }
  .stat-box { display: inline-block; background: #161b22; color: #c9d1d9; padding: 10px 15px; margin: 5px; border-radius: 6px; text-align: center; min-width: 100px; }
  .stat-value { font-size: 20pt; font-weight: bold; color: #58a6ff; }
  .stat-label { font-size: 8pt; color: #8b949e; }
  .alert { color: #f85149; font-weight: bold; }
  .warning { color: #d29922; }
  .safe { color: #3fb950; }
  .footer { margin-top: 30px; padding-top: 10px; border-top: 2px solid #30363d; font-size: 7pt; color: #8b949e; }
  .attribution { font-style: italic; margin: 2px 0; }
  .triage-isolated { background: #f8514922; }
  .triage-degraded { background: #d2992222; }
  .page-break { page-break-before: always; }
</style>
</head>
<body>

<h1>🛰️ S.T.R.A.N.D — Situation Report</h1>
<p><strong>Disaster:</strong> {{ disaster_type }} — {{ disaster_date }}<br>
<strong>Analysis ID:</strong> {{ analysis_id }}<br>
<strong>Generated:</strong> {{ generated_at }}<br>
<strong>Status:</strong> {{ status }}</p>

{% if 'summary' in sections %}
<h2>📊 Executive Summary</h2>
<div>
  <div class="stat-box"><div class="stat-value">{{ stats.flood_area_km2 | default('—') }}</div><div class="stat-label">Flood Area (km²)</div></div>
  <div class="stat-box"><div class="stat-value">{{ stats.roads_severed_km | default('—') }}</div><div class="stat-label">Roads Severed (km)</div></div>
  <div class="stat-box"><div class="stat-value">{{ stats.bridges_destroyed | default('—') }}</div><div class="stat-label">Bridges Destroyed</div></div>
  <div class="stat-box"><div class="stat-value">{{ stats.buildings_submerged | default('—') }}</div><div class="stat-label">Buildings Submerged</div></div>
  <div class="stat-box"><div class="stat-value alert">{{ stats.settlements_isolated | default('—') }}</div><div class="stat-label">Settlements Isolated</div></div>
  <div class="stat-box"><div class="stat-value">{{ stats.hlz_count | default('—') }}</div><div class="stat-label">HLZ Candidates</div></div>
</div>
{% endif %}

{% if 'damage_table' in sections %}
<h2>🏗️ Infrastructure Damage Summary</h2>
<table>
  <tr><th>Asset Type</th><th>Total</th><th>Intact</th><th>Damaged</th><th>Destroyed/Severed</th></tr>
  <tr>
    <td>Roads (km)</td>
    <td>{{ stats.roads_total_km | default('—') }}</td>
    <td>{{ (stats.roads_total_km or 0) - (stats.roads_severed_km or 0) - (stats.roads_partial_km or 0) | round(1) }}</td>
    <td class="warning">{{ stats.roads_partial_km | default('—') }}</td>
    <td class="alert">{{ stats.roads_severed_km | default('—') }}</td>
  </tr>
  <tr>
    <td>Bridges</td>
    <td>{{ stats.bridges_total | default('—') }}</td>
    <td>{{ (stats.bridges_total or 0) - (stats.bridges_destroyed or 0) - (stats.bridges_damaged or 0) }}</td>
    <td class="warning">{{ stats.bridges_damaged | default('—') }}</td>
    <td class="alert">{{ stats.bridges_destroyed | default('—') }}</td>
  </tr>
  <tr>
    <td>Buildings</td>
    <td>{{ stats.buildings_total | default('—') }}</td>
    <td>{{ (stats.buildings_total or 0) - (stats.buildings_submerged or 0) - (stats.buildings_contact or 0) }}</td>
    <td class="warning">{{ stats.buildings_contact | default('—') }}</td>
    <td class="alert">{{ stats.buildings_submerged | default('—') }}</td>
  </tr>
</table>
{% endif %}

{% if 'isolation' in sections %}
<h2 class="page-break">🚨 Settlement Isolation Triage</h2>
<table>
  <tr><th>#</th><th>Settlement</th><th>Status</th><th>Pop. Est.</th><th>Urgency</th><th>Hub Dist (km)</th></tr>
  {% for s in settlements %}
  <tr class="triage-{{ s.isolation_status }}">
    <td>{{ loop.index }}</td>
    <td>{{ s.name | default('Unknown') }}</td>
    <td>{% if s.isolation_status == 'isolated' %}<span class="alert">ISOLATED</span>{% elif s.isolation_status == 'degraded' %}<span class="warning">DEGRADED</span>{% else %}<span class="safe">CONNECTED</span>{% endif %}</td>
    <td>{{ s.estimated_population | default('—') }}</td>
    <td>{{ '%.2f' | format(s.urgency_score) if s.urgency_score else '—' }}</td>
    <td>{{ '%.1f' | format(s.post_disaster_hub_dist_m / 1000) if s.post_disaster_hub_dist_m and s.post_disaster_hub_dist_m < 1e10 else '∞' }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if 'hlz' in sections and hlz_sites %}
<h2>🚁 Helicopter Landing Zone Candidates</h2>
<table>
  <tr><th>#</th><th>Slope</th><th>Area (m²)</th><th>Elevation</th><th>Surface</th><th>Nearest Settlement (km)</th></tr>
  {% for h in hlz_sites %}
  <tr>
    <td>{{ loop.index }}</td>
    <td>{{ '%.1f°' | format(h.avg_slope_deg) }}</td>
    <td>{{ h.area_m2 | int }}</td>
    <td>{{ h.elevation_m | int }}m</td>
    <td>{{ h.surface_estimate | default('—') }}</td>
    <td>{{ '%.1f' | format(h.dist_to_settlement_m / 1000) if h.dist_to_settlement_m else '—' }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if 'limitations' in sections %}
<h2>⚠️ Limitations & Warnings</h2>
<ul>
{% for w in warnings %}
  <li>{{ w }}</li>
{% endfor %}
  <li>Flood extent derived from SAR change detection — cloud-penetrating but lower spatial resolution than optical.</li>
  <li>Population estimates use Nepal average household size (4.5 persons/building) — actual values may differ.</li>
  <li>OSM data quality varies in remote mountain regions — some roads and buildings may be unmapped.</li>
</ul>
{% endif %}

<div class="footer">
  <strong>Legal Attributions:</strong><br>
  {% for attr in attributions %}
  <p class="attribution">{{ attr }}</p>
  {% endfor %}
  <p>Generated by S.T.R.A.N.D v1.0 — Satellite Terrain Response & Network Damage System</p>
</div>

</body>
</html>"""


def generate_sitrep_pdf(
    analysis_id: str,
    output_dir: Path | str,
    language: str = "en",
    sections: list[str] | None = None,
) -> Path:
    """
    Generate a PDF Situation Report for an analysis.

    Args:
        analysis_id: The analysis ID.
        output_dir: Directory to save the PDF.
        language: Report language ('en' or 'ne').
        sections: Sections to include (defaults to all).

    Returns:
        Path to the generated PDF file.
    """
    logger.info("Generating SitRep PDF for analysis %s", analysis_id)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if sections is None:
        sections = ["summary", "flood_map", "damage_table", "isolation", "hlz", "limitations"]

    # Gather data
    summary = get_analysis_summary(analysis_id) or {}
    warnings = get_analysis_warnings(analysis_id)
    stats = compute_analysis_statistics(analysis_id)

    # Get settlements (sorted by urgency)
    from strand.db.connection import get_db
    db = get_db()
    settlement_rows = db.execute(
        """
        SELECT name, isolation_status, estimated_population, urgency_score,
               post_disaster_hub_dist_m
        FROM settlements
        WHERE analysis_id = ?
        ORDER BY urgency_score DESC NULLS LAST
        """,
        [analysis_id],
    ).fetchall()

    settlements = [
        {
            "name": r[0], "isolation_status": r[1],
            "estimated_population": r[2], "urgency_score": r[3],
            "post_disaster_hub_dist_m": r[4],
        }
        for r in settlement_rows
    ]

    # Get HLZ sites
    hlz_rows = db.execute(
        """
        SELECT avg_slope_deg, area_m2, elevation_m, surface_estimate, dist_to_settlement_m
        FROM hlz_sites WHERE analysis_id = ? ORDER BY dist_to_settlement_m ASC LIMIT 10
        """,
        [analysis_id],
    ).fetchall()

    hlz_sites = [
        {
            "avg_slope_deg": r[0], "area_m2": r[1], "elevation_m": r[2],
            "surface_estimate": r[3], "dist_to_settlement_m": r[4],
        }
        for r in hlz_rows
    ]

    # Render HTML
    env = Environment(autoescape=True)
    template = env.from_string(SITREP_HTML_TEMPLATE)

    html = template.render(
        analysis_id=analysis_id,
        disaster_type="Glacier Collapse / Flash Flood",
        disaster_date=summary.get("disaster_date", "2026-08-26"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        status=summary.get("status", "unknown"),
        language=language,
        sections=sections,
        stats=stats,
        settlements=settlements,
        hlz_sites=hlz_sites,
        warnings=warnings,
        attributions=ALL_ATTRIBUTIONS,
    )

    # Convert to PDF
    output_path = output_dir / f"sitrep_{analysis_id[:8]}.pdf"

    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(output_path))
        logger.info("SitRep PDF generated: %s", output_path)
    except ImportError:
        # Fallback: save HTML
        output_path = output_dir / f"sitrep_{analysis_id[:8]}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.warning(
            "WeasyPrint not available. Saved HTML instead: %s", output_path
        )

    return output_path
