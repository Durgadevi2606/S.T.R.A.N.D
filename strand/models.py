"""
S.T.R.A.N.D — Pydantic Data Models & Schemas

Defines all request/response schemas, domain entities, and validation logic
used across the API, pipeline, and database layers.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from strand.config import (
    MAX_AOI_AREA_KM2,
    SENTINEL1_LAUNCH_DATE,
    bbox_area_km2,
    auto_detect_utm_for_bbox,
)


# ─── Enums ───────────────────────────────────────────────────

class AnalysisStatus(str, Enum):
    """Pipeline execution status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class PipelinePhase(str, Enum):
    """Pipeline processing phases."""
    INGESTION = "ingestion"
    PREPROCESSING = "preprocessing"
    SEGMENTATION = "segmentation"
    OPTICAL_VALIDATION = "optical_validation"
    INFRASTRUCTURE_OVERLAY = "infrastructure_overlay"
    NETWORK_ANALYSIS = "network_analysis"
    TACTICAL_MODULES = "tactical_modules"


class PhaseStatus(str, Enum):
    """Individual phase status."""
    PENDING = "pending"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RoadDamageClass(str, Enum):
    """Road segment damage classification."""
    INTACT = "intact"
    PARTIALLY_FLOODED = "partially_flooded"
    SEVERED = "severed"


class BridgeDamageClass(str, Enum):
    """Bridge damage classification."""
    INTACT = "intact"
    DAMAGED = "damaged"
    DESTROYED = "destroyed"


class BuildingDamageClass(str, Enum):
    """Building damage classification."""
    SAFE = "safe"
    FLOOD_CONTACT = "flood_contact"
    SUBMERGED = "submerged"


class IsolationStatus(str, Enum):
    """Settlement connectivity status."""
    ISOLATED = "isolated"
    DEGRADED = "degraded"
    CONNECTED = "connected"


class PondingRiskLevel(str, Enum):
    """Debris dam ponding breach risk level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DetectionMethod(str, Enum):
    """Flood detection method used."""
    THRESHOLD = "threshold"
    UNET = "unet"
    ENSEMBLE = "ensemble"


# ─── Request Schemas ─────────────────────────────────────────

class AOIBbox(BaseModel):
    """
    Area of Interest bounding box in WGS84 coordinates.

    Validates that coordinates are within valid ranges and that
    the bounding box area does not exceed the maximum allowed.
    """

    north: float = Field(..., ge=-90, le=90, description="Northern latitude boundary")
    south: float = Field(..., ge=-90, le=90, description="Southern latitude boundary")
    east: float = Field(..., ge=-180, le=180, description="Eastern longitude boundary")
    west: float = Field(..., ge=-180, le=180, description="Western longitude boundary")

    @model_validator(mode="after")
    def validate_bbox_geometry(self) -> "AOIBbox":
        """Ensure north > south, east > west, and area within limits."""
        if self.north <= self.south:
            raise ValueError(
                f"North ({self.north}) must be greater than south ({self.south})"
            )
        if self.east <= self.west:
            raise ValueError(
                f"East ({self.east}) must be greater than west ({self.west})"
            )
        area = bbox_area_km2(self.west, self.south, self.east, self.north)
        if area > MAX_AOI_AREA_KM2:
            raise ValueError(
                f"AOI area ({area:.0f} km²) exceeds maximum of "
                f"{MAX_AOI_AREA_KM2:.0f} km²"
            )
        return self

    @property
    def area_km2(self) -> float:
        """Approximate bounding box area in km²."""
        return bbox_area_km2(self.west, self.south, self.east, self.north)

    @property
    def center(self) -> tuple[float, float]:
        """Bounding box centroid as (lon, lat)."""
        return ((self.west + self.east) / 2, (self.south + self.north) / 2)

    @property
    def utm_zone(self) -> int:
        """Auto-detected UTM zone number."""
        zone, _ = auto_detect_utm_for_bbox(self.west, self.south, self.east, self.north)
        return zone

    @property
    def utm_epsg(self) -> int:
        """Auto-detected UTM EPSG code (e.g. 32645 for Zone 45N)."""
        _, epsg = auto_detect_utm_for_bbox(self.west, self.south, self.east, self.north)
        return epsg

    def to_wkt(self) -> str:
        """Convert to WKT POLYGON string."""
        return (
            f"POLYGON(({self.west} {self.south}, {self.east} {self.south}, "
            f"{self.east} {self.north}, {self.west} {self.north}, "
            f"{self.west} {self.south}))"
        )

    def to_list(self) -> list[float]:
        """Return as [west, south, east, north] list for API calls."""
        return [self.west, self.south, self.east, self.north]


class CollapseOrigin(BaseModel):
    """Optional upstream glacier collapse origin point."""

    lat: float = Field(..., ge=-90, le=90, description="Latitude of collapse origin")
    lon: float = Field(..., ge=-180, le=180, description="Longitude of collapse origin")


class UrgencyWeights(BaseModel):
    """Configurable weights for the settlement urgency scoring formula."""

    population: float = Field(default=0.40, ge=0, le=1, description="Population weight")
    flood_proximity: float = Field(default=0.35, ge=0, le=1, description="Flood proximity weight")
    clinic_penalty: float = Field(default=0.25, ge=0, le=1, description="Clinic penalty weight")

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "UrgencyWeights":
        """Weights should sum to approximately 1.0."""
        total = self.population + self.flood_proximity + self.clinic_penalty
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Urgency weights must sum to 1.0, got {total:.2f}"
            )
        return self


class AnalysisOptions(BaseModel):
    """Optional configuration for an analysis pipeline run."""

    run_optical_validation: bool = Field(
        default=True, description="Attempt Sentinel-2 MNDWI cross-validation"
    )
    run_hlz_finder: bool = Field(
        default=True, description="Run helicopter landing zone finder"
    )
    run_ponding_detector: bool = Field(
        default=True, description="Run debris dam ponding detector"
    )
    run_flow_tracer: bool = Field(
        default=False, description="Run D8 flow-path tracer (requires collapse_origin)"
    )
    urgency_weights: UrgencyWeights = Field(
        default_factory=UrgencyWeights,
        description="Weights for settlement urgency scoring",
    )


class AnalysisRequest(BaseModel):
    """Request to trigger a new flood damage analysis pipeline."""

    aoi_bbox: AOIBbox = Field(..., description="Area of interest bounding box")
    disaster_date: date = Field(..., description="Date of the disaster event")
    collapse_origin: CollapseOrigin | None = Field(
        default=None,
        description="Optional upstream glacier collapse origin for flow tracing",
    )
    options: AnalysisOptions = Field(
        default_factory=AnalysisOptions,
        description="Pipeline configuration options",
    )

    @field_validator("disaster_date")
    @classmethod
    def validate_disaster_date(cls, v: date) -> date:
        """Disaster date must be between S1 launch and today."""
        from datetime import date as date_type

        s1_launch = date_type.fromisoformat(SENTINEL1_LAUNCH_DATE)
        if v < s1_launch:
            raise ValueError(
                f"Disaster date {v} is before Sentinel-1 launch ({SENTINEL1_LAUNCH_DATE})"
            )
        if v > date_type.today():
            raise ValueError(f"Disaster date {v} is in the future")
        return v

    @model_validator(mode="after")
    def validate_collapse_origin_in_aoi(self) -> "AnalysisRequest":
        """If collapse_origin is provided, it must be within the AOI."""
        if self.collapse_origin is not None:
            bbox = self.aoi_bbox
            origin = self.collapse_origin
            if not (bbox.south <= origin.lat <= bbox.north):
                raise ValueError(
                    f"Collapse origin latitude {origin.lat} is outside AOI "
                    f"[{bbox.south}, {bbox.north}]"
                )
            if not (bbox.west <= origin.lon <= bbox.east):
                raise ValueError(
                    f"Collapse origin longitude {origin.lon} is outside AOI "
                    f"[{bbox.west}, {bbox.east}]"
                )
        if self.options.run_flow_tracer and self.collapse_origin is None:
            raise ValueError(
                "Flow tracer requires a collapse_origin point to be specified"
            )
        return self


# ─── Response Schemas ────────────────────────────────────────

class PhaseInfo(BaseModel):
    """Status of a single pipeline phase."""

    name: str
    status: PhaseStatus
    duration_sec: float | None = None
    message: str | None = None


class AnalysisSummary(BaseModel):
    """Aggregate statistics from a completed analysis."""

    flood_area_km2: float | None = None
    roads_total_km: float | None = None
    roads_severed_km: float | None = None
    roads_partially_flooded_km: float | None = None
    bridges_total: int | None = None
    bridges_destroyed: int | None = None
    bridges_damaged: int | None = None
    buildings_total: int | None = None
    buildings_submerged: int | None = None
    buildings_flood_contact: int | None = None
    settlements_total: int | None = None
    settlements_isolated: int | None = None
    settlements_degraded: int | None = None
    hlz_candidates: int | None = None
    ponding_zones: int | None = None


class AnalysisMetadata(BaseModel):
    """Satellite data metadata for an analysis."""

    sar_pre_date: date | None = None
    sar_post_date: date | None = None
    orbit_number: int | None = None
    orbit_direction: str | None = None
    s2_available: bool = False
    osm_snapshot: str | None = None
    utm_epsg: int | None = None


class AnalysisResponse(BaseModel):
    """Full response for an analysis, including status and results."""

    analysis_id: str
    status: AnalysisStatus
    progress_pct: float = 0.0
    current_phase: str | None = None
    phases: list[PhaseInfo] = []
    summary: AnalysisSummary | None = None
    metadata: AnalysisMetadata | None = None
    warnings: list[str] = []
    created_at: datetime
    completed_at: datetime | None = None


class AnalysisCreatedResponse(BaseModel):
    """Response when a new analysis is queued."""

    analysis_id: str
    status: AnalysisStatus = AnalysisStatus.QUEUED
    estimated_duration_min: int = 43
    websocket_url: str
    created_at: datetime


class AnalysisListItem(BaseModel):
    """Summary item for the analysis list endpoint."""

    analysis_id: str
    status: AnalysisStatus
    disaster_date: date
    flood_area_km2: float | None = None
    created_at: datetime


class AnalysisListResponse(BaseModel):
    """Paginated list of analyses."""

    total: int
    analyses: list[AnalysisListItem]


# ─── Copilot Schemas ─────────────────────────────────────────

class CopilotQueryRequest(BaseModel):
    """Request to the bilingual copilot."""

    query: str = Field(..., max_length=500, description="Natural language question")
    language: str = Field(default="en", description="Query language: 'en' or 'ne'")

    @field_validator("query")
    @classmethod
    def validate_query_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Query cannot be empty")
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        if v not in ("en", "ne"):
            raise ValueError("Language must be 'en' (English) or 'ne' (Nepali)")
        return v


class SQLCitation(BaseModel):
    """SQL query citation for copilot transparency."""

    sql: str
    raw_result: dict[str, Any]
    executed_at: datetime


class CopilotQueryResponse(BaseModel):
    """Response from the bilingual copilot."""

    answer: str
    language: str
    citation: SQLCitation | None = None
    hallucination_check: bool = True
    confidence: str = "high"


# ─── Export Schemas ──────────────────────────────────────────

class SitRepRequest(BaseModel):
    """Request to generate a PDF Situation Report."""

    language: str = Field(default="en", description="Primary language")
    include_nepali: bool = Field(default=True, description="Include Nepali translation")
    sections: list[str] = Field(
        default=[
            "summary", "flood_map", "damage_table",
            "isolation", "hlz", "limitations",
        ],
        description="Sections to include",
    )
    map_dpi: int = Field(default=300, ge=72, le=600, description="Map rendering DPI")


class MBTilesRequest(BaseModel):
    """Request to generate offline MBTiles map package."""

    zoom_min: int = Field(default=10, ge=0, le=22, description="Minimum zoom level")
    zoom_max: int = Field(default=16, ge=0, le=22, description="Maximum zoom level")
    layers: list[str] = Field(
        default=["flood", "roads", "settlements", "hlz"],
        description="Layers to include",
    )
    basemap: str = Field(default="osm", description="Basemap source")

    @model_validator(mode="after")
    def validate_zoom_range(self) -> "MBTilesRequest":
        if self.zoom_min > self.zoom_max:
            raise ValueError("zoom_min must be ≤ zoom_max")
        return self


class SMSAlertRequest(BaseModel):
    """Request to generate a compressed SMS/LoRa alert string."""

    template: str = Field(default="bridge_isolation", description="Alert template name")
    max_chars: int = Field(default=140, ge=50, le=280, description="Max character count")
    include_hlz: bool = Field(default=True, description="Include nearest HLZ coordinates")
    settlement_ids: list[str] = Field(
        default=[], description="Specific settlement IDs to include"
    )


class SMSAlertResponse(BaseModel):
    """Generated SMS alert string."""

    alert_text: str
    char_count: int
    truncated: bool


# ─── Telemetry Schemas ───────────────────────────────────────

class SatelliteOverpass(BaseModel):
    """Information about an upcoming satellite overpass."""

    satellite: str
    datetime_utc: datetime
    track: str | None = None
    orbit_number: int | None = None
    aoi_coverage_pct: float | None = None
    cloud_risk: str | None = None
    countdown_seconds: int


class RevisitResponse(BaseModel):
    """List of upcoming satellite overpasses for the AOI."""

    next_overpasses: list[SatelliteOverpass]
    generated_at: datetime


# ─── Health Schemas ──────────────────────────────────────────

class HealthResponse(BaseModel):
    """System health check response."""

    status: str = "healthy"
    version: str
    database: str
    redis: str
    gpu_available: bool
    gpu_memory_mb: int | None = None
    disk_free_gb: float | None = None
    uptime_seconds: int


# ─── WebSocket Schemas ───────────────────────────────────────

class WSProgressMessage(BaseModel):
    """WebSocket progress update message."""

    type: str = "progress"
    phase: str
    status: str
    progress_pct: float
    message: str
    timestamp: datetime


class WSCompleteMessage(BaseModel):
    """WebSocket pipeline completion message."""

    type: str = "complete"
    analysis_id: str
    summary: AnalysisSummary
    timestamp: datetime


class WSErrorMessage(BaseModel):
    """WebSocket error message."""

    type: str = "error"
    phase: str
    message: str
    recoverable: bool
    timestamp: datetime


# ─── Error Schemas ───────────────────────────────────────────

class ErrorDetail(BaseModel):
    """Structured error response."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Wrapped error response."""

    error: ErrorDetail


# ─── Auth Schemas ───────────────────────────────────────────

class OperatorRole(str, Enum):
    """Operator functional roles in mission theater."""
    COMMANDER = "commander"
    ANALYST = "analyst"
    FIELD_OPS = "field_ops"
    LOGISTICS = "logistics"


class LoginRequest(BaseModel):
    """Operator authentication request schema."""
    callsign: str = Field(..., min_length=2, max_length=50, description="Operator callsign")
    api_key: str = Field(..., min_length=1, description="Security access API key")
    role: OperatorRole = Field(default=OperatorRole.COMMANDER, description="Assigned mission role")
    theater: str = Field(default="EMSR-927", description="Operational Theater code")


class OperatorProfile(BaseModel):
    """Authenticated operator metadata."""
    callsign: str
    role: str
    role_display: str
    clearance_level: str
    theater: str
    token: str
    authenticated_at: datetime
    permissions: list[str]


class LoginResponse(BaseModel):
    """Successful login response."""
    authenticated: bool
    operator: OperatorProfile
    message: str

