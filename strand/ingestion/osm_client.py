"""
S.T.R.A.N.D — OpenStreetMap ohsome API Client

Fetches pre-disaster infrastructure vectors from the ohsome API
(api.ohsome.org/v1) using temporal snapshots.

Key design decisions:
- Uses snapshot timestamps STRICTLY before the disaster date (hackathon rule).
- Enforces the OSM_SNAPSHOT_CUTOFF to prevent accidental use of post-disaster edits.
- Extracts roads, bridges, buildings, healthcare facilities, and settlements
  with full tag preservation.
- Returns GeoJSON FeatureCollections ready for GeoPandas ingestion.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from strand.config import OSM_SNAPSHOT_CUTOFF, get_settings

logger = logging.getLogger(__name__)

OHSOME_BASE_URL = "https://api.ohsome.org/v1"

# Maximum retries for API calls
MAX_RETRIES = 3
BACKOFF_BASE_S = 2

# ohsome rate limit: ~5 req/min for heavy queries
RATE_LIMIT_DELAY_S = 1.5


class OhsomeAPIError(Exception):
    """Raised when ohsome API requests fail."""


class OhsomeTimestampError(Exception):
    """Raised when attempting to use a post-disaster OSM timestamp."""


class OhsomeClient:
    """
    Client for the ohsome OpenStreetMap History Analytics API.

    Provides methods to fetch pre-event snapshots of infrastructure
    features within a given bounding box.
    """

    def __init__(self, snapshot_timestamp: str | None = None) -> None:
        """
        Initialize the ohsome client.

        Args:
            snapshot_timestamp: ISO 8601 timestamp for the OSM snapshot.
                                Must be before the disaster date.
                                Defaults to '2026-07-27T00:00:00Z'.
        """
        self._base_url = OHSOME_BASE_URL

        if snapshot_timestamp is None:
            # Default: 30 days before the disaster
            self._timestamp = "2026-07-27T00:00:00Z"
        else:
            self._timestamp = snapshot_timestamp

        # Validate timestamp is before the cutoff
        self._validate_timestamp(self._timestamp)

        self._http = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=30.0),  # ohsome can be slow for large areas
            follow_redirects=True,
        )

        logger.info("ohsome client initialized with snapshot: %s", self._timestamp)

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    # ─── Timestamp Validation ────────────────────────────────

    @staticmethod
    def _validate_timestamp(timestamp: str) -> None:
        """
        Enforce the hackathon rule: OSM data must be from BEFORE the disaster.

        The cutoff is 2026-08-27T00:00:00Z (day after the disaster).
        Using post-event OSM edits is STRICTLY FORBIDDEN and leads to disqualification.

        Raises:
            OhsomeTimestampError: If timestamp is on or after the cutoff.
        """
        try:
            ts = datetime.fromisoformat(timestamp.rstrip("Z"))
            cutoff = datetime.fromisoformat(OSM_SNAPSHOT_CUTOFF.rstrip("Z"))
            if ts >= cutoff:
                raise OhsomeTimestampError(
                    f"OSM snapshot timestamp {timestamp} is on or after the disaster cutoff "
                    f"({OSM_SNAPSHOT_CUTOFF}). Using post-disaster OSM data is FORBIDDEN "
                    f"by hackathon rules and will lead to DISQUALIFICATION."
                )
        except ValueError as e:
            raise OhsomeTimestampError(
                f"Invalid timestamp format: {timestamp}. Use ISO 8601 format."
            ) from e

    # ─── Feature Extraction Methods ──────────────────────────

    def fetch_roads(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch all road geometries (highway=*) within the bounding box.

        Returns LineString/MultiLineString geometries with full OSM tags.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM roads for bbox %s at %s", bbox, self._timestamp)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="highway=* and type:way",
            geometry_type="geometry",
        )

    def fetch_bridges(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch all bridge geometries (bridge=yes) within the bounding box.

        Returns both point and linestring bridge features.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM bridges for bbox %s at %s", bbox, self._timestamp)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="bridge=yes and type:way",
            geometry_type="geometry",
        )

    def fetch_buildings(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch all building footprints (building=*) within the bounding box.

        Returns Polygon geometries with building type tags.

        Note: For very large AOIs, buildings can be numerous (>100K).
        Consider spatial sub-tiling for AOIs > 50 km².

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM buildings for bbox %s at %s", bbox, self._timestamp)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="building=* and type:way",
            geometry_type="geometry",
        )

    def fetch_healthcare(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch healthcare facilities (hospitals, clinics, pharmacies).

        These serve as "hub nodes" in the graph reachability analysis.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM healthcare for bbox %s at %s", bbox, self._timestamp)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="amenity in (hospital, clinic, pharmacy, doctors) and (type:node or type:way)",
            geometry_type="centroid",
        )

    def fetch_settlements(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch settlement points (villages, towns, cities).

        Used as settlement nodes in the isolation analysis.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM settlements for bbox %s at %s", bbox, self._timestamp)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="place in (village, town, city, hamlet) and type:node",
            geometry_type="geometry",
        )

    def fetch_forests(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch forest/woodland areas for HLZ exclusion.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM forests for bbox %s", bbox)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="landuse=forest or natural=wood and type:way",
            geometry_type="geometry",
        )

    def fetch_power_lines(
        self,
        bbox: list[float],
    ) -> dict[str, Any]:
        """
        Fetch power line geometries for HLZ exclusion.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        logger.info("Fetching OSM power lines for bbox %s", bbox)
        return self._fetch_elements(
            bbox=bbox,
            osm_filter="power=line and type:way",
            geometry_type="geometry",
        )

    def fetch_all_infrastructure(
        self,
        bbox: list[float],
    ) -> dict[str, dict[str, Any]]:
        """
        Fetch all infrastructure layers in one call.

        Returns a dict keyed by layer name, each containing a GeoJSON FeatureCollection.
        Respects rate limiting between queries.

        Args:
            bbox: [west, south, east, north] in WGS84.

        Returns:
            Dict mapping layer names to GeoJSON FeatureCollections.
        """
        logger.info("Fetching all OSM infrastructure layers...")

        results = {}

        fetch_methods = [
            ("roads", self.fetch_roads),
            ("bridges", self.fetch_bridges),
            ("buildings", self.fetch_buildings),
            ("healthcare", self.fetch_healthcare),
            ("settlements", self.fetch_settlements),
            ("forests", self.fetch_forests),
            ("power_lines", self.fetch_power_lines),
        ]

        for name, method in fetch_methods:
            try:
                results[name] = method(bbox)
                feature_count = len(results[name].get("features", []))
                logger.info("  %s: %d features", name, feature_count)
                # Rate limiting
                time.sleep(RATE_LIMIT_DELAY_S)
            except OhsomeAPIError as e:
                logger.error("Failed to fetch %s: %s", name, e)
                results[name] = {"type": "FeatureCollection", "features": []}

        return results

    # ─── Core API Call ───────────────────────────────────────

    def _fetch_elements(
        self,
        bbox: list[float],
        osm_filter: str,
        geometry_type: str = "geometry",
    ) -> dict[str, Any]:
        """
        Execute an ohsome elements/geometry query.

        Args:
            bbox: [west, south, east, north].
            osm_filter: ohsome filter expression (e.g., 'highway=*').
            geometry_type: 'geometry', 'centroid', or 'bbox'.

        Returns:
            GeoJSON FeatureCollection dict.

        Raises:
            OhsomeAPIError: If the query fails after retries.
        """
        endpoint = f"{self._base_url}/elements/{geometry_type}"
        bbox_str = ",".join(str(c) for c in bbox)

        data = {
            "bboxes": bbox_str,
            "filter": osm_filter,
            "time": self._timestamp,
            "properties": "tags",
            "clipGeometry": "true",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._http.post(
                    endpoint,
                    data=data,
                    headers={"Accept": "application/geo+json"},
                )
                response.raise_for_status()
                geojson = response.json()

                # Validate it's a proper GeoJSON
                if geojson.get("type") != "FeatureCollection":
                    logger.warning("Unexpected response type: %s", geojson.get("type"))
                    return {"type": "FeatureCollection", "features": []}

                return geojson

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "ohsome query attempt %d/%d failed: HTTP %s — %s",
                    attempt, MAX_RETRIES, e.response.status_code,
                    e.response.text[:200] if e.response.text else "no body",
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

            except httpx.RequestError as e:
                logger.warning(
                    "ohsome query attempt %d/%d network error: %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_S ** attempt)

        raise OhsomeAPIError(
            f"ohsome query failed after {MAX_RETRIES} attempts. "
            f"Filter: {osm_filter}, bbox: {bbox_str}"
        )


# ─── Utility Functions ───────────────────────────────────────

def geojson_to_geodataframe(geojson: dict[str, Any]) -> Any:
    """
    Convert a GeoJSON FeatureCollection to a GeoPandas GeoDataFrame.

    Preserves all properties as columns and sets CRS to EPSG:4326.

    Args:
        geojson: GeoJSON FeatureCollection dict.

    Returns:
        GeoPandas GeoDataFrame with geometry and property columns.
    """
    import geopandas as gpd

    if not geojson.get("features"):
        # Return empty GeoDataFrame with expected columns
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")

    # Extract tags from nested 'properties' if present
    if "@osmId" in gdf.columns:
        # ohsome returns OSM IDs with prefix (way/123456)
        gdf["osm_id"] = gdf["@osmId"].apply(
            lambda x: int(x.split("/")[-1]) if isinstance(x, str) and "/" in x else None
        )

    return gdf
