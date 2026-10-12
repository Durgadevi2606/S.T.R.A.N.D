"""
S.T.R.A.N.D — Global Configuration Module

Loads environment variables and provides typed, validated configuration
for all system components. Uses pydantic-settings for automatic .env parsing.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CDSESettings(BaseSettings):
    """Copernicus Data Space Ecosystem API configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CDSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str = Field(default="", description="CDSE OAuth2 client ID")
    client_secret: str = Field(default="", description="CDSE OAuth2 client secret")
    auth_url: str = Field(
        default="https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        description="CDSE OAuth2 token endpoint",
    )
    odata_url: str = Field(
        default="https://catalogue.dataspace.copernicus.eu/odata/v1",
        description="CDSE OData catalog API base URL",
    )
    download_url: str = Field(
        default="https://download.dataspace.copernicus.eu/odata/v1",
        description="CDSE product download base URL",
    )


class GeminiSettings(BaseSettings):
    """Google Gemini LLM configuration for the Copilot module."""

    model_config = SettingsConfigDict(
        env_prefix="GEMINI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(default="", description="Gemini API key")
    model: str = Field(default="gemini-flash-lite-latest", description="Gemini model name")


class StrandSettings(BaseSettings):
    """
    Master configuration for the S.T.R.A.N.D system.

    Loads values from environment variables and .env files.
    All paths are resolved relative to the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API Server ---
    strand_api_keys: list[str] = Field(
        default=["dev-key-change-in-production"],
        description="List of valid API keys for authentication",
    )
    strand_host: str = Field(default="0.0.0.0", description="API bind host")
    strand_port: int = Field(default=8000, description="API bind port")

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Celery broker",
    )

    # --- Database ---
    database_url: str = Field(
        default="",
        description="PostgreSQL / Neon connection URL (e.g. postgresql://...)",
    )
    database_path: str = Field(
        default="./data/strand.duckdb",
        description="Path to DuckDB database file (used if database_url is empty)",
    )

    # --- Data Directories ---
    data_dir: str = Field(default="./data", description="Root data directory")
    raw_data_dir: str = Field(default="./data/raw", description="Raw satellite downloads")
    processed_data_dir: str = Field(default="./data/processed", description="Processed rasters")
    vector_data_dir: str = Field(default="./data/vectors", description="Vector data")
    tiles_dir: str = Field(default="./data/tiles", description="Map tile cache")
    reports_dir: str = Field(default="./data/reports", description="Generated reports")

    # --- ML ---
    model_checkpoint_dir: str = Field(
        default="./ml/checkpoints",
        description="ML model checkpoint directory",
    )

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="./logs/strand.log", description="Log file path")

    # --- Sub-configs ---
    cdse: CDSESettings = Field(default_factory=CDSESettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)

    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        dirs = [
            self.data_dir,
            self.raw_data_dir,
            self.processed_data_dir,
            self.vector_data_dir,
            self.tiles_dir,
            self.reports_dir,
            self.model_checkpoint_dir,
            os.path.dirname(self.log_file),
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)

    def get_analysis_dir(self, analysis_id: str) -> Path:
        """Get the data directory for a specific analysis run."""
        path = Path(self.processed_data_dir) / analysis_id
        path.mkdir(parents=True, exist_ok=True)
        return path


# ─── CRS & Projection Utilities ─────────────────────────────

def auto_detect_utm_zone(lon: float, lat: float) -> tuple[int, int]:
    """
    Determine the UTM zone number and EPSG code for a given WGS84 coordinate.

    Args:
        lon: Longitude in decimal degrees (-180 to 180).
        lat: Latitude in decimal degrees (-90 to 90).

    Returns:
        Tuple of (zone_number, epsg_code).
        For Nepal (~85°E, ~28°N) this returns (45, 32645) → UTM Zone 45N.
    """
    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        epsg = 32600 + zone_number  # Northern hemisphere
    else:
        epsg = 32700 + zone_number  # Southern hemisphere
    return zone_number, epsg


def auto_detect_utm_for_bbox(
    west: float, south: float, east: float, north: float
) -> tuple[int, int]:
    """
    Determine UTM zone for a bounding box using its centroid.

    Args:
        west, south, east, north: Bounding box in WGS84 degrees.

    Returns:
        Tuple of (zone_number, epsg_code).
    """
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    return auto_detect_utm_zone(center_lon, center_lat)


def bbox_area_km2(
    west: float, south: float, east: float, north: float
) -> float:
    """
    Approximate bounding box area in km² using the Haversine-based formula.

    Accounts for latitude-dependent east-west distance.

    Args:
        west, south, east, north: Bounding box in WGS84 degrees.

    Returns:
        Approximate area in square kilometers.
    """
    lat_km = (north - south) * 111.32
    mid_lat_rad = math.radians((north + south) / 2)
    lon_km = (east - west) * 111.32 * math.cos(mid_lat_rad)
    return abs(lat_km * lon_km)


# ─── Constants ───────────────────────────────────────────────

# Maximum allowed AOI area (km²)
MAX_AOI_AREA_KM2 = 40_000.0

# Sentinel-1 launch date (earliest valid disaster date)
SENTINEL1_LAUNCH_DATE = "2014-04-03"

# Nepal average household size for population estimation
NEPAL_AVG_HOUSEHOLD_SIZE = 4.5

# OSM snapshot cutoff — must be before the disaster
OSM_SNAPSHOT_CUTOFF = "2026-08-27T00:00:00Z"

# DEM resolution
DEM_RESOLUTION_M = 30.0

# HLZ criteria
HLZ_MAX_SLOPE_DEG = 5.0
HLZ_MIN_AREA_M2 = 900.0  # 30m × 30m
HLZ_MAX_ELEVATION_M = 5000.0

# Road damage classification thresholds
ROAD_PARTIAL_FLOOD_THRESHOLD = 0.01  # > 1% flooded = partially flooded
ROAD_SEVERED_THRESHOLD = 0.50  # > 50% flooded = severed

# Bridge buffer radius for damage assessment
BRIDGE_BUFFER_RADIUS_M = 50.0

# Building flood contact thresholds
BUILDING_FLOOD_CONTACT_THRESHOLD = 0.01  # > 1%
BUILDING_SUBMERGED_THRESHOLD = 0.30  # > 30%

# Graph analysis
SETTLEMENT_SNAP_DISTANCE_M = 500.0  # Max snap distance to nearest road
DEGRADED_PATH_MULTIPLIER = 3.0  # Path > 3× pre-disaster = degraded

# Urgency score default weights
URGENCY_W_POPULATION = 0.40
URGENCY_W_FLOOD_PROXIMITY = 0.35
URGENCY_W_CLINIC_PENALTY = 0.25

# Ponding volume threshold (m³) for alerting
PONDING_VOLUME_THRESHOLD_M3 = 500_000.0

# SMS character limit
SMS_MAX_CHARS = 140

# Morphological cleanup
MIN_FLOOD_COMPONENT_PIXELS = 500  # ~0.5 hectares at 10m resolution
SLOPE_FALSE_POSITIVE_THRESHOLD_DEG = 30.0  # Remove flood detections on steep slopes

# Mandatory legal attributions
ATTRIBUTION_SENTINEL = (
    'Contains modified Copernicus Sentinel data 2026.'
)
ATTRIBUTION_DEM = (
    'Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 '
    'and © Airbus Defence and Space GmbH 2014–2018 provided under '
    'COPERNICUS by the European Union and ESA; all rights reserved.'
)
ATTRIBUTION_OSM = '© OpenStreetMap contributors.'
ATTRIBUTION_KURO_SIWO = (
    'Kuro Siwo dataset (MIT License): Bountos et al., '
    '"Kuro Siwo: 33 billion m² Desktop Labeled SAR dataset for global flood mapping", 2024.'
)
ATTRIBUTION_SEN1FLOODS11 = (
    'Sen1Floods11 dataset (CC BY 4.0): Bonafilia et al., '
    '"Sen1Floods11: a georeferenced dataset to train and test deep learning '
    'flood algorithms for Sentinel-1", 2020.'
)
ATTRIBUTION_EMSR927 = (
    'Copernicus EMS Rapid Mapping Activation EMSR927 used as offline '
    'validation benchmark only (not as model input).'
)

ALL_ATTRIBUTIONS = [
    ATTRIBUTION_SENTINEL,
    ATTRIBUTION_DEM,
    ATTRIBUTION_OSM,
    ATTRIBUTION_KURO_SIWO,
    ATTRIBUTION_SEN1FLOODS11,
    ATTRIBUTION_EMSR927,
]


# ─── Singleton Settings Instance ─────────────────────────────

_settings: StrandSettings | None = None


def get_settings() -> StrandSettings:
    """Get the global settings singleton. Loads from .env on first call."""
    global _settings
    if _settings is None:
        _settings = StrandSettings()
    return _settings
