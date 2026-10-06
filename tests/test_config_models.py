"""
S.T.R.A.N.D — Tests: Configuration & Models

Tests the config constants, settings loading, UTM detection,
AOI validation, and Pydantic schema enforcement.
"""

import math
from datetime import date

import pytest

from strand.config import (
    ALL_ATTRIBUTIONS,
    BRIDGE_BUFFER_RADIUS_M,
    BUILDING_FLOOD_CONTACT_THRESHOLD,
    BUILDING_SUBMERGED_THRESHOLD,
    DEGRADED_PATH_MULTIPLIER,
    HLZ_MAX_SLOPE_DEG,
    HLZ_MIN_AREA_M2,
    MAX_AOI_AREA_KM2,
    MIN_FLOOD_COMPONENT_PIXELS,
    NEPAL_AVG_HOUSEHOLD_SIZE,
    PONDING_VOLUME_THRESHOLD_M3,
    ROAD_PARTIAL_FLOOD_THRESHOLD,
    ROAD_SEVERED_THRESHOLD,
    SETTLEMENT_SNAP_DISTANCE_M,
    SLOPE_FALSE_POSITIVE_THRESHOLD_DEG,
    SMS_MAX_CHARS,
    URGENCY_W_CLINIC_PENALTY,
    URGENCY_W_FLOOD_PROXIMITY,
    URGENCY_W_POPULATION,
    auto_detect_utm_for_bbox,
    auto_detect_utm_zone,
    bbox_area_km2,
)


class TestConstants:
    """Verify all hardcoded constants have sensible values."""

    def test_household_size(self):
        assert NEPAL_AVG_HOUSEHOLD_SIZE == 4.5

    def test_hlz_slope_limit(self):
        assert 0 < HLZ_MAX_SLOPE_DEG <= 10

    def test_hlz_min_area(self):
        assert HLZ_MIN_AREA_M2 >= 400  # At least 20m × 20m

    def test_road_thresholds_order(self):
        assert ROAD_PARTIAL_FLOOD_THRESHOLD < ROAD_SEVERED_THRESHOLD

    def test_building_thresholds_order(self):
        assert BUILDING_FLOOD_CONTACT_THRESHOLD < BUILDING_SUBMERGED_THRESHOLD

    def test_urgency_weights_sum(self):
        total = URGENCY_W_POPULATION + URGENCY_W_FLOOD_PROXIMITY + URGENCY_W_CLINIC_PENALTY
        assert abs(total - 1.0) < 1e-6, f"Urgency weights must sum to 1.0, got {total}"

    def test_sms_char_limit(self):
        assert SMS_MAX_CHARS == 140

    def test_attributions_not_empty(self):
        assert len(ALL_ATTRIBUTIONS) >= 5, "Must have all 5+ legal attributions"

    def test_slope_threshold_reasonable(self):
        assert 15 <= SLOPE_FALSE_POSITIVE_THRESHOLD_DEG <= 45

    def test_degraded_multiplier(self):
        assert DEGRADED_PATH_MULTIPLIER >= 2.0

    def test_min_flood_component(self):
        assert MIN_FLOOD_COMPONENT_PIXELS > 0

    def test_ponding_threshold(self):
        assert PONDING_VOLUME_THRESHOLD_M3 > 0


class TestUTMDetection:
    """Test automatic UTM zone detection."""

    def test_nepal_kathmandu(self):
        zone, epsg = auto_detect_utm_zone(85.3, 27.7)
        assert zone == "45N"
        assert epsg == 32645

    def test_nepal_west(self):
        zone, epsg = auto_detect_utm_zone(80.5, 28.5)
        assert zone == "44N"
        assert epsg == 32644

    def test_southern_hemisphere(self):
        zone, epsg = auto_detect_utm_zone(150.0, -33.8)  # Sydney
        assert "S" in zone
        assert epsg >= 32700

    def test_bbox_utm(self):
        zone, epsg = auto_detect_utm_for_bbox(85.0, 27.5, 86.0, 28.5)
        assert epsg == 32645


class TestBboxArea:
    """Test bounding box area computation."""

    def test_known_area(self):
        # ~1° × 1° near equator ≈ 12,300 km²
        area = bbox_area_km2(0, 0, 1, 1)
        assert 10000 < area < 15000

    def test_nepal_aoi(self):
        area = bbox_area_km2(85.0, 27.5, 86.0, 28.5)
        assert 5000 < area < 15000

    def test_zero_area(self):
        area = bbox_area_km2(85.0, 27.5, 85.0, 27.5)
        assert area == 0


class TestPydanticModels:
    """Test Pydantic schema validation."""

    def test_aoi_bbox_valid(self):
        from strand.models import AOIBbox
        aoi = AOIBbox(west=85.0, south=27.5, east=86.0, north=28.5)
        assert aoi.area_km2 > 0
        assert aoi.center_lon == pytest.approx(85.5, abs=0.01)

    def test_aoi_bbox_invalid_bounds(self):
        from strand.models import AOIBbox
        with pytest.raises(Exception):
            AOIBbox(west=86.0, south=27.5, east=85.0, north=28.5)  # west > east

    def test_aoi_bbox_too_large(self):
        from strand.models import AOIBbox
        with pytest.raises(Exception):
            AOIBbox(west=70.0, south=20.0, east=90.0, north=35.0)  # Way too large

    def test_analysis_request_valid(self):
        from strand.models import AnalysisRequest, AOIBbox
        req = AnalysisRequest(
            aoi_bbox=AOIBbox(west=85.0, south=27.5, east=85.5, north=28.0),
            disaster_date=date(2026, 8, 26),
        )
        assert req.disaster_date == date(2026, 8, 26)

    def test_analysis_status_enum(self):
        from strand.models import AnalysisStatus
        assert AnalysisStatus.QUEUED == "queued"
        assert AnalysisStatus.COMPLETE == "complete"

    def test_sitrep_request_defaults(self):
        from strand.models import SitRepRequest
        req = SitRepRequest()
        assert req.language == "en"
        assert "summary" in req.sections

    def test_sms_alert_request(self):
        from strand.models import SMSAlertRequest
        req = SMSAlertRequest(max_chars=160)
        assert req.max_chars == 160
