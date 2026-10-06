"""
S.T.R.A.N.D — SMS / LoRa Alert Composer

Generates compressed text alerts for SMS (140-char) and LoRa
transmission to isolated communities without internet connectivity.

Templates are designed for maximum information density within
the character limit, using standardized abbreviations.
"""

from __future__ import annotations

import logging
from typing import Any

from strand.config import SMS_MAX_CHARS

logger = logging.getLogger(__name__)


# Standard abbreviations for compact alerts
ABBREV = {
    "bridge": "BRG",
    "road": "RD",
    "destroyed": "DESTR",
    "damaged": "DMG",
    "isolated": "ISOL",
    "settlement": "SETL",
    "helicopter": "HELI",
    "population": "POP",
    "estimated": "EST",
    "kilometers": "KM",
    "meters": "M",
    "elevation": "ELEV",
    "coordinate": "COORD",
}


# Alert templates
TEMPLATES = {
    "bridge_isolation": (
        "ALERT: {settlement} ISOL. BRG {bridge} DESTR. "
        "POP~{pop}. HLZ@{hlz_lat},{hlz_lon} {hlz_elev}m. "
        "NextSAR:{next_pass}."
    ),
    "road_severed": (
        "ALERT: RD {road} SEVERED {pct}%. "
        "{n_isolated} SETL cut off. "
        "ALT route +{detour_km}km. "
        "NextSAR:{next_pass}."
    ),
    "general_summary": (
        "STRAND: Flood {area}km2. "
        "RD sev {rd_sev}km. "
        "BRG destr {brg_d}. "
        "ISOL {n_isol} SETL. "
        "HLZ {n_hlz} sites."
    ),
    "ponding_warning": (
        "⚠PONDING: {vol}m3 @{lat},{lon}. "
        "RISK:{risk}. "
        "DAM ELEV {elev}m. "
        "DOWNSTREAM ALERT."
    ),
    "hlz_dispatch": (
        "HLZ: {lat},{lon} ELEV{elev}m. "
        "SLOPE{slope}°. "
        "AREA{area}m2. "
        "NEAR:{settlement} {dist}km. "
        "SURFACE:{surface}."
    ),
}


def compose_sms_alert(
    template_name: str,
    data: dict[str, Any],
    max_chars: int = SMS_MAX_CHARS,
) -> dict[str, Any]:
    """
    Compose an SMS alert from a template and data.

    Applies progressive truncation if the message exceeds max_chars:
    1. First, remove optional fields
    2. Then, abbreviate remaining text
    3. Finally, truncate with "..." indicator

    Args:
        template_name: Name of the alert template.
        data: Dict of values to populate the template.
        max_chars: Maximum character count (default 140 for SMS).

    Returns:
        Dict with alert_text, char_count, and truncated flag.
    """
    if template_name not in TEMPLATES:
        template_name = "general_summary"

    template = TEMPLATES[template_name]

    # Populate template with data
    try:
        alert = template.format(**data)
    except KeyError as e:
        logger.warning("Missing template field %s, using defaults", e)
        # Fill missing keys with "?"
        filled_data = {k: data.get(k, "?") for k in _extract_template_keys(template)}
        alert = template.format(**filled_data)

    # Truncate if needed
    truncated = False
    if len(alert) > max_chars:
        alert = alert[: max_chars - 3] + "..."
        truncated = True

    result = {
        "alert_text": alert,
        "char_count": len(alert),
        "truncated": truncated,
    }

    logger.info(
        "SMS alert [%s]: %d chars%s",
        template_name, result["char_count"],
        " (TRUNCATED)" if truncated else "",
    )

    return result


def compose_settlement_alerts(
    settlements: list[dict[str, Any]],
    hlz_sites: list[dict[str, Any]] | None = None,
    max_chars: int = SMS_MAX_CHARS,
) -> list[dict[str, Any]]:
    """
    Generate SMS alerts for each isolated settlement.

    Args:
        settlements: List of settlement dicts (from DB or GeoDataFrame).
        hlz_sites: Optional list of HLZ candidate dicts.
        max_chars: Maximum characters per alert.

    Returns:
        List of alert dicts (one per isolated settlement).
    """
    alerts = []

    for settlement in settlements:
        status = settlement.get("isolation_status", "connected")
        if status == "connected":
            continue

        # Find nearest HLZ
        hlz_lat, hlz_lon, hlz_elev = "?", "?", "?"
        if hlz_sites:
            nearest = hlz_sites[0]  # Already sorted by proximity
            hlz_lat = f"{nearest.get('centroid_y', 0):.4f}"
            hlz_lon = f"{nearest.get('centroid_x', 0):.4f}"
            hlz_elev = str(int(nearest.get("elevation_m", 0)))

        data = {
            "settlement": (settlement.get("name", "?"))[:15],
            "bridge": "nearest",
            "pop": str(settlement.get("estimated_population", "?")),
            "hlz_lat": hlz_lat,
            "hlz_lon": hlz_lon,
            "hlz_elev": hlz_elev,
            "next_pass": "TBD",
        }

        alert = compose_sms_alert("bridge_isolation", data, max_chars)
        alert["settlement_id"] = settlement.get("id")
        alert["settlement_name"] = settlement.get("name")
        alerts.append(alert)

    logger.info("Generated %d settlement SMS alerts", len(alerts))
    return alerts


def compose_summary_alert(
    stats: dict[str, Any],
    max_chars: int = SMS_MAX_CHARS,
) -> dict[str, Any]:
    """
    Generate a single summary SMS alert with overall statistics.

    Args:
        stats: Analysis statistics dict.
        max_chars: Maximum characters.

    Returns:
        Alert dict.
    """
    data = {
        "area": str(round(stats.get("flood_area_km2", 0), 1)),
        "rd_sev": str(round(stats.get("roads_severed_km", 0), 1)),
        "brg_d": str(stats.get("bridges_destroyed", 0)),
        "n_isol": str(stats.get("settlements_isolated", 0)),
        "n_hlz": str(stats.get("hlz_count", 0)),
    }

    return compose_sms_alert("general_summary", data, max_chars)


def _extract_template_keys(template: str) -> list[str]:
    """Extract format key names from a template string."""
    import re
    return re.findall(r"\{(\w+)\}", template)
