"""
S.T.R.A.N.D — Tests: Pipeline Orchestrator & Storage

Tests PipelineOrchestrator initialization, GeoDataFrame transformations,
database persistence methods, progress updates, and pipeline execution.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from strand.db.connection import get_db
from strand.db.migrations import run_migrations
from strand.db.spatial_queries import get_analysis_summary
from strand.models import AnalysisOptions, AnalysisRequest, AOIBbox
from strand.pipeline.orchestrator import PipelineOrchestrator, run_pipeline
from tests.conftest import UTM_CRS


@pytest.fixture
def sample_request():
    """Create a standard AnalysisRequest for testing."""
    return AnalysisRequest(
        aoi_bbox=AOIBbox(west=85.85, south=27.75, east=86.00, north=28.00),
        disaster_date=date(2026, 8, 26),
        options=AnalysisOptions(
            enable_unet=False,
            enable_optical_validation=False,
            enable_ponding=True,
            enable_hlz=True,
        ),
    )


class TestPipelineOrchestratorInit:
    """Test pipeline orchestrator construction and configuration."""

    def test_orchestrator_initialization(self, sample_request, tmp_dir):
        orchestrator = PipelineOrchestrator(
            analysis_id="test-orch-001",
            request=sample_request,
            work_dir=tmp_dir / "work",
        )
        assert orchestrator.analysis_id == "test-orch-001"
        assert orchestrator.utm_zone == 45
        assert orchestrator.utm_epsg == 32645
        assert orchestrator.work_dir.exists()

    def test_features_to_geodataframe(self, sample_request, tmp_dir):
        orchestrator = PipelineOrchestrator(
            analysis_id="test-orch-002",
            request=sample_request,
            work_dir=tmp_dir,
        )
        features = [
            {
                "type": "Feature",
                "properties": {"name": "Test Feature", "value": 42},
                "geometry": {
                    "type": "Point",
                    "coordinates": [85.90, 27.85],
                },
            }
        ]
        gdf = orchestrator._features_to_geodataframe(features, src_epsg=4326)
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 1
        assert gdf.iloc[0]["name"] == "Test Feature"
        assert gdf.crs.to_epsg() == 32645

    def test_features_to_geodataframe_empty(self, sample_request, tmp_dir):
        orchestrator = PipelineOrchestrator(
            analysis_id="test-orch-003",
            request=sample_request,
            work_dir=tmp_dir,
        )
        gdf = orchestrator._features_to_geodataframe([])
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 0


class TestPipelineDatabasePersistence:
    """Test orchestrator database persistence operations."""

    def test_create_and_update_status(self, sample_request, tmp_dir):
        run_migrations()
        db = get_db()
        analysis_id = "test-persist-001"

        orchestrator = PipelineOrchestrator(
            analysis_id=analysis_id,
            request=sample_request,
            work_dir=tmp_dir,
        )

        # Create record
        orchestrator._create_analysis_record(db)
        summary = get_analysis_summary(analysis_id)
        assert summary is not None
        assert summary["status"] == "queued"
        assert summary["progress_pct"] == 0.0

        # Update status
        orchestrator._update_status(db, "processing", 50.0, "sar_preprocessing")
        summary_updated = get_analysis_summary(analysis_id)
        assert summary_updated["status"] == "processing"
        assert summary_updated["progress_pct"] == 50.0
        assert summary_updated["current_phase"] == "sar_preprocessing"

    def test_store_infrastructure_entities(
        self,
        sample_request,
        tmp_dir,
        roads_gdf,
        bridges_gdf,
        buildings_gdf,
        settlements_gdf,
        healthcare_gdf,
    ):
        run_migrations()
        db = get_db()
        analysis_id = "test-persist-infra"

        orchestrator = PipelineOrchestrator(
            analysis_id=analysis_id,
            request=sample_request,
            work_dir=tmp_dir,
        )
        orchestrator._create_analysis_record(db)

        # Store entities
        orchestrator._store_roads(roads_gdf)
        orchestrator._store_bridges(bridges_gdf)
        orchestrator._store_buildings(buildings_gdf)
        orchestrator._store_settlements(settlements_gdf)
        orchestrator._store_hubs(healthcare_gdf)

        # Verify counts in DuckDB
        roads_count = db.execute(
            "SELECT COUNT(*) FROM road_segments WHERE analysis_id = ?",
            [analysis_id],
        ).fetchone()[0]
        assert roads_count == len(roads_gdf)

        bridges_count = db.execute(
            "SELECT COUNT(*) FROM bridges WHERE analysis_id = ?",
            [analysis_id],
        ).fetchone()[0]
        assert bridges_count == len(bridges_gdf)

        settlements_count = db.execute(
            "SELECT COUNT(*) FROM settlements WHERE analysis_id = ?",
            [analysis_id],
        ).fetchone()[0]
        assert settlements_count == len(settlements_gdf)

        hubs_count = db.execute(
            "SELECT COUNT(*) FROM hub_nodes WHERE analysis_id = ?",
            [analysis_id],
        ).fetchone()[0]
        assert hubs_count == len(healthcare_gdf)
