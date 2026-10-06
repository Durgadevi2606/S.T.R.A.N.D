"""
S.T.R.A.N.D — Pipeline Orchestrator

Chains all processing modules into an end-to-end analysis pipeline.
Designed to run as a Celery task or synchronously for testing.

Pipeline phases:
1. INGESTION: Download SAR pair, DEM, and OSM infrastructure
2. PREPROCESSING: Calibrate, terrain-correct, co-register SAR
3. SEGMENTATION: Log-ratio, threshold, U-Net, ensemble, morphology, vectorize
4. OPTICAL_VALIDATION: MNDWI cross-validation (if Sentinel-2 available)
5. INFRASTRUCTURE_OVERLAY: Road/bridge/building damage classification
6. NETWORK_ANALYSIS: Graph build, reachability, urgency scoring
7. TACTICAL_MODULES: HLZ finder, ponding detector (optional)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio

from strand.config import get_settings, auto_detect_utm_for_bbox, NEPAL_AVG_HOUSEHOLD_SIZE
from strand.db.connection import get_db
from strand.db.spatial_queries import (
    add_analysis_warning,
    compute_analysis_statistics,
    log_pipeline_phase,
)
from strand.models import (
    AnalysisOptions,
    AnalysisRequest,
    AnalysisStatus,
    AOIBbox,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the full S.T.R.A.N.D analysis pipeline.

    Each phase is tracked in the database with status and timing.
    WebSocket progress updates are emitted via the progress_callback.
    """

    def __init__(
        self,
        analysis_id: str,
        request: AnalysisRequest,
        progress_callback: callable | None = None,
    ):
        self.analysis_id = analysis_id
        self.request = request
        self.aoi = request.aoi_bbox
        self.disaster_date = request.disaster_date
        self.options = request.options
        self.progress_callback = progress_callback

        settings = get_settings()
        self.data_dir = Path(settings.processed_data_dir) / analysis_id
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Determine UTM zone
        _, self.utm_epsg = auto_detect_utm_for_bbox(
            self.aoi.west, self.aoi.south, self.aoi.east, self.aoi.north
        )

        self.warnings: list[str] = []
        self.phase_timings: dict[str, float] = {}

    def run(self) -> dict[str, Any]:
        """
        Execute the full pipeline end-to-end.

        Returns:
            Dict with analysis_id, status, summary statistics, and warnings.
        """
        logger.info("=" * 70)
        logger.info(
            "PIPELINE START: analysis=%s, disaster=%s, utm=EPSG:%d",
            self.analysis_id, self.disaster_date, self.utm_epsg,
        )
        logger.info(
            "AOI: [%.4f, %.4f, %.4f, %.4f] (%.0f km²)",
            self.aoi.west, self.aoi.south, self.aoi.east, self.aoi.north,
            self.aoi.area_km2,
        )
        logger.info("=" * 70)

        pipeline_start = time.monotonic()
        db = get_db()

        try:
            # Create analysis record
            self._create_analysis_record(db)
            self._update_status(db, "running", 0.0, "ingestion")

            # Phase 1: Ingestion
            ingestion_data = self._phase_ingestion()

            # Phase 2: Preprocessing
            preprocessed = self._phase_preprocessing(ingestion_data)

            # Phase 3: Segmentation
            flood_data = self._phase_segmentation(preprocessed)

            # Phase 4: Optical validation (optional)
            if self.options.run_optical_validation and ingestion_data.get("s2_available"):
                self._phase_optical_validation(flood_data, ingestion_data)

            # Phase 5: Infrastructure overlay
            infrastructure = self._phase_infrastructure_overlay(
                flood_data, ingestion_data
            )

            # Phase 6: Network analysis
            self._phase_network_analysis(infrastructure, flood_data, ingestion_data)

            # Phase 7: Tactical modules (optional)
            if self.options.run_hlz_finder or self.options.run_ponding_detector:
                self._phase_tactical_modules(flood_data, preprocessed, ingestion_data)

            # Compute final statistics
            stats = compute_analysis_statistics(self.analysis_id)
            self._update_analysis_stats(db, stats)
            self._update_status(db, "complete", 100.0, None)

            # Store warnings
            for w in self.warnings:
                add_analysis_warning(self.analysis_id, w)

            total_time = time.monotonic() - pipeline_start
            logger.info("=" * 70)
            logger.info(
                "PIPELINE COMPLETE: %s in %.1f seconds (%.1f min)",
                self.analysis_id, total_time, total_time / 60,
            )
            logger.info("Phase timings:")
            for phase, duration in self.phase_timings.items():
                logger.info("  %s: %.1fs", phase, duration)
            logger.info("=" * 70)

            return {
                "analysis_id": self.analysis_id,
                "status": "complete",
                "summary": stats,
                "warnings": self.warnings,
                "duration_sec": round(total_time, 1),
            }

        except Exception as e:
            logger.error("PIPELINE FAILED: %s — %s", self.analysis_id, e, exc_info=True)
            self._update_status(db, "failed", 0.0, None)
            log_pipeline_phase(self.analysis_id, "error", "failed", str(e))
            raise

    # ─── Phase Implementations ───────────────────────────────

    def _phase_ingestion(self) -> dict[str, Any]:
        """Phase 1: Download SAR pair, DEM, and OSM data."""
        phase_start = time.monotonic()
        self._emit_progress("ingestion", "started", 5, "Downloading satellite data...")
        log_pipeline_phase(self.analysis_id, "ingestion", "started")

        settings = get_settings()
        bbox = self.aoi.to_list()
        result: dict[str, Any] = {"s2_available": False}

        # --- SAR pair ---
        try:
            from strand.ingestion.cdse_client import CDSEClient

            cdse = CDSEClient()
            pre_prod, post_prod = cdse.find_sar_pair(
                bbox=bbox, disaster_date=self.disaster_date
            )

            if pre_prod and post_prod:
                pre_path = cdse.download_product(
                    pre_prod["Id"], settings.raw_data_dir, pre_prod.get("Name")
                )
                post_path = cdse.download_product(
                    post_prod["Id"], settings.raw_data_dir, post_prod.get("Name")
                )
                result["pre_sar_path"] = pre_path
                result["post_sar_path"] = post_path
                result["pre_product"] = pre_prod
                result["post_product"] = post_prod
            else:
                raise RuntimeError("No matching SAR pair found for the AOI and date range")

            # --- DEM ---
            dem_paths = cdse.download_dem30(bbox, Path(settings.raw_data_dir) / "dem")
            result["dem_paths"] = dem_paths

            # --- Sentinel-2 (optional) ---
            if self.options.run_optical_validation:
                from datetime import timedelta
                s2_products = cdse.search_sentinel2_l2a(
                    bbox=bbox,
                    start_date=self.disaster_date + timedelta(days=1),
                    end_date=self.disaster_date + timedelta(days=30),
                    max_cloud_pct=30.0,
                    max_results=5,
                )
                if s2_products:
                    result["s2_available"] = True
                    result["s2_product"] = s2_products[0]
                else:
                    self.warnings.append(
                        "No cloud-free Sentinel-2 imagery available. "
                        "Optical cross-validation skipped."
                    )

            cdse.close()

        except Exception as e:
            logger.error("Ingestion failed: %s", e)
            log_pipeline_phase(self.analysis_id, "ingestion", "failed", str(e))
            raise

        # --- OSM data ---
        try:
            from strand.ingestion.osm_client import OhsomeClient, geojson_to_geodataframe

            osm = OhsomeClient()
            osm_data = osm.fetch_all_infrastructure(bbox)
            result["osm_data"] = {
                name: geojson_to_geodataframe(geojson)
                for name, geojson in osm_data.items()
            }
            osm.close()
        except Exception as e:
            logger.error("OSM fetch failed: %s", e)
            self.warnings.append(f"OSM data fetch partially failed: {e}")
            result["osm_data"] = {}

        self.phase_timings["ingestion"] = time.monotonic() - phase_start
        self._emit_progress("ingestion", "completed", 15, "Data downloaded")
        log_pipeline_phase(self.analysis_id, "ingestion", "completed")

        return result

    def _phase_preprocessing(self, ingestion: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Calibrate, terrain-correct, and co-register SAR."""
        phase_start = time.monotonic()
        self._emit_progress("preprocessing", "started", 20, "Preprocessing SAR imagery...")
        log_pipeline_phase(self.analysis_id, "preprocessing", "started")

        from strand.ingestion.sar_preprocessor import SARPreprocessor, preprocess_dem

        # Mosaic DEM tiles
        dem_path = preprocess_dem(
            dem_paths=ingestion["dem_paths"],
            aoi_bounds=self.aoi.to_list(),
            utm_epsg=self.utm_epsg,
            output_dir=self.data_dir,
        )

        # Process SAR pair
        preprocessor = SARPreprocessor(
            utm_epsg=self.utm_epsg, output_dir=self.data_dir
        )
        processed = preprocessor.process_pair(
            pre_path=ingestion["pre_sar_path"],
            post_path=ingestion["post_sar_path"],
            dem_path=dem_path,
            aoi_bounds=self.aoi.to_list(),
        )

        processed["dem_path"] = dem_path

        self.phase_timings["preprocessing"] = time.monotonic() - phase_start
        self._emit_progress("preprocessing", "completed", 35, "SAR preprocessed")
        log_pipeline_phase(self.analysis_id, "preprocessing", "completed")

        return processed

    def _phase_segmentation(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        """Phase 3: Flood detection — threshold + U-Net + ensemble."""
        phase_start = time.monotonic()
        self._emit_progress("segmentation", "started", 40, "Detecting flood extent...")
        log_pipeline_phase(self.analysis_id, "segmentation", "started")

        from strand.segmentation.change_detection import (
            apply_slope_mask,
            compute_log_ratio_from_files,
            otsu_threshold,
        )
        from strand.segmentation.ensemble import (
            ensemble_vote,
            morphological_cleanup,
            save_flood_mask_geotiff,
            vectorize_flood_mask,
        )
        from strand.segmentation.unet_model import FloodInference

        # Compute log-ratios
        lr_vv_path = self.data_dir / "log_ratio_vv.tif"
        lr_vh_path = self.data_dir / "log_ratio_vh.tif"

        compute_log_ratio_from_files(
            preprocessed["pre_vv"], preprocessed["post_vv"], lr_vv_path
        )
        compute_log_ratio_from_files(
            preprocessed["pre_vh"], preprocessed["post_vh"], lr_vh_path
        )

        # Read log-ratios
        with rasterio.open(lr_vv_path) as ds:
            lr_vv = ds.read(1)
            profile = ds.profile.copy()
            transform = ds.transform
            crs = ds.crs

        with rasterio.open(lr_vh_path) as ds:
            lr_vh = ds.read(1)

        # Threshold-based detection
        thresh_mask_vv = otsu_threshold(lr_vv, invert=True)
        thresh_mask_vh = otsu_threshold(lr_vh, invert=True)

        # U-Net inference
        settings = get_settings()
        checkpoint = Path(settings.model_checkpoint_dir) / "flood_unet.pt"
        inference = FloodInference(
            checkpoint_path=checkpoint if checkpoint.exists() else None
        )
        unet_prob = inference.predict(lr_vv, lr_vh)

        # Ensemble vote
        flood_mask, confidence = ensemble_vote(
            thresh_mask_vv, thresh_mask_vh, unet_prob
        )

        # Slope masking (remove radar shadow false positives)
        flood_mask = apply_slope_mask(flood_mask, preprocessed["dem_path"])

        # Morphological cleanup
        flood_mask = morphological_cleanup(flood_mask)

        # Save rasters
        mask_path, conf_path = save_flood_mask_geotiff(
            flood_mask, confidence, preprocessed["pre_vv"], self.data_dir
        )

        # Vectorize
        flood_features = vectorize_flood_mask(flood_mask, transform, crs)

        # Store in database
        self._store_flood_polygons(flood_features)

        result = {
            "mask_path": mask_path,
            "confidence_path": conf_path,
            "flood_mask": flood_mask,
            "flood_features": flood_features,
            "transform": transform,
            "crs": crs,
        }

        self.phase_timings["segmentation"] = time.monotonic() - phase_start
        self._emit_progress("segmentation", "completed", 55, "Flood extent mapped")
        log_pipeline_phase(self.analysis_id, "segmentation", "completed")

        return result

    def _phase_optical_validation(
        self, flood_data: dict, ingestion: dict
    ) -> None:
        """Phase 4: Optional MNDWI cross-validation."""
        phase_start = time.monotonic()
        self._emit_progress("optical_validation", "started", 58, "Cross-validating with optical...")
        log_pipeline_phase(self.analysis_id, "optical_validation", "started")

        try:
            from strand.segmentation.optical_validation import validate_sar_with_mndwi
            # Would download and process S2 here
            self.warnings.append("Optical cross-validation: implementation pending S2 download")
            log_pipeline_phase(self.analysis_id, "optical_validation", "skipped",
                             "S2 processing not yet implemented")
        except Exception as e:
            self.warnings.append(f"Optical validation failed: {e}")
            log_pipeline_phase(self.analysis_id, "optical_validation", "failed", str(e))

        self.phase_timings["optical_validation"] = time.monotonic() - phase_start

    def _phase_infrastructure_overlay(
        self, flood_data: dict, ingestion: dict
    ) -> dict[str, Any]:
        """Phase 5: Road/bridge/building damage classification."""
        phase_start = time.monotonic()
        self._emit_progress("infrastructure_overlay", "started", 60,
                          "Assessing infrastructure damage...")
        log_pipeline_phase(self.analysis_id, "infrastructure_overlay", "started")

        from strand.overlay.bridge_damage import classify_bridge_damage
        from strand.overlay.building_damage import classify_building_damage, estimate_affected_population
        from strand.overlay.road_damage import classify_road_damage

        osm = ingestion.get("osm_data", {})

        # Build flood GeoDataFrame from stored features
        flood_gdf = self._features_to_geodataframe(
            flood_data["flood_features"], flood_data["crs"]
        )

        # Reproject OSM layers to UTM
        roads_gdf = osm.get("roads", gpd.GeoDataFrame())
        bridges_gdf = osm.get("bridges", gpd.GeoDataFrame())
        buildings_gdf = osm.get("buildings", gpd.GeoDataFrame())

        from pyproj import CRS as PyprojCRS
        utm_crs = PyprojCRS.from_epsg(self.utm_epsg)

        if not roads_gdf.empty:
            roads_gdf = roads_gdf.to_crs(utm_crs)
            roads_gdf["length_m"] = roads_gdf.geometry.length
        if not bridges_gdf.empty:
            bridges_gdf = bridges_gdf.to_crs(utm_crs)
        if not buildings_gdf.empty:
            buildings_gdf = buildings_gdf.to_crs(utm_crs)
        if not flood_gdf.empty:
            flood_gdf = flood_gdf.to_crs(utm_crs)

        # Classify damage
        roads_classified = classify_road_damage(roads_gdf, flood_gdf)
        bridges_classified = classify_bridge_damage(bridges_gdf, flood_gdf)
        buildings_classified = classify_building_damage(buildings_gdf, flood_gdf)

        # Population estimate
        pop_estimate = estimate_affected_population(buildings_classified)

        # Store in database
        self._store_roads(roads_classified)
        self._store_bridges(bridges_classified)
        self._store_buildings(buildings_classified)

        result = {
            "roads": roads_classified,
            "bridges": bridges_classified,
            "buildings": buildings_classified,
            "population_estimate": pop_estimate,
        }

        self.phase_timings["infrastructure_overlay"] = time.monotonic() - phase_start
        self._emit_progress("infrastructure_overlay", "completed", 75,
                          "Infrastructure assessed")
        log_pipeline_phase(self.analysis_id, "infrastructure_overlay", "completed")

        return result

    def _phase_network_analysis(
        self, infrastructure: dict, flood_data: dict, ingestion: dict
    ) -> None:
        """Phase 6: Graph reachability and urgency scoring."""
        phase_start = time.monotonic()
        self._emit_progress("network_analysis", "started", 78,
                          "Analyzing settlement isolation...")
        log_pipeline_phase(self.analysis_id, "network_analysis", "started")

        from strand.network_graph.graph_builder import (
            build_pre_disaster_graph,
            build_road_graph,
            snap_points_to_graph,
        )
        from strand.network_graph.reachability import (
            classify_isolation,
            compute_pre_disaster_distances,
        )
        from strand.network_graph.urgency_scorer import compute_urgency_scores

        roads = infrastructure["roads"]
        osm = ingestion.get("osm_data", {})
        settlements_gdf = osm.get("settlements", gpd.GeoDataFrame())
        healthcare_gdf = osm.get("healthcare", gpd.GeoDataFrame())

        if settlements_gdf.empty:
            self.warnings.append("No settlement data available for isolation analysis")
            log_pipeline_phase(self.analysis_id, "network_analysis", "skipped",
                             "No settlements")
            return

        # Reproject to UTM
        from pyproj import CRS as PyprojCRS
        utm_crs = PyprojCRS.from_epsg(self.utm_epsg)
        settlements_gdf = settlements_gdf.to_crs(utm_crs)
        if not healthcare_gdf.empty:
            healthcare_gdf = healthcare_gdf.to_crs(utm_crs)

        # Assign IDs and population estimates
        if "id" not in settlements_gdf.columns:
            settlements_gdf["id"] = [str(uuid.uuid4()) for _ in range(len(settlements_gdf))]
        if "estimated_population" not in settlements_gdf.columns:
            settlements_gdf["estimated_population"] = int(NEPAL_AVG_HOUSEHOLD_SIZE * 20)

        if "id" not in healthcare_gdf.columns and not healthcare_gdf.empty:
            healthcare_gdf["id"] = [str(uuid.uuid4()) for _ in range(len(healthcare_gdf))]

        # Build graphs
        post_graph = build_road_graph(roads)
        pre_graph = build_pre_disaster_graph(roads)

        # Snap settlements and hubs to graph
        settlement_snapped = snap_points_to_graph(
            post_graph, settlements_gdf, label_column="name"
        )
        hub_snapped = snap_points_to_graph(
            post_graph, healthcare_gdf, label_column="name"
        )

        # Pre-disaster distances
        pre_settlement_snapped = snap_points_to_graph(
            pre_graph, settlements_gdf, label_column="name"
        )
        pre_hub_snapped = snap_points_to_graph(
            pre_graph, healthcare_gdf, label_column="name"
        )
        pre_distances = compute_pre_disaster_distances(
            pre_graph, pre_settlement_snapped, pre_hub_snapped
        )

        # Classify isolation
        isolation_results = classify_isolation(
            post_graph, settlement_snapped, hub_snapped,
            pre_distances=pre_distances,
        )

        # Compute urgency scores
        flood_gdf = self._features_to_geodataframe(
            flood_data["flood_features"], flood_data["crs"]
        )
        if not flood_gdf.empty:
            flood_gdf = flood_gdf.to_crs(utm_crs)

        settlements_scored = compute_urgency_scores(
            settlements_gdf, isolation_results, flood_gdf
        )

        # Update settlements with isolation results
        for s_id, result in isolation_results.items():
            mask = settlements_scored["id"] == s_id
            if mask.any():
                settlements_scored.loc[mask, "isolation_status"] = result["status"]
                settlements_scored.loc[mask, "post_disaster_hub_dist_m"] = result["post_distance_m"]
                settlements_scored.loc[mask, "pre_disaster_hub_dist_m"] = result.get("pre_distance_m")

        # Store in database
        self._store_settlements(settlements_scored)
        self._store_hubs(healthcare_gdf)

        self.phase_timings["network_analysis"] = time.monotonic() - phase_start
        self._emit_progress("network_analysis", "completed", 90,
                          "Isolation analysis complete")
        log_pipeline_phase(self.analysis_id, "network_analysis", "completed")

    def _phase_tactical_modules(
        self, flood_data: dict, preprocessed: dict, ingestion: dict
    ) -> None:
        """Phase 7: HLZ finder and ponding detection."""
        phase_start = time.monotonic()
        self._emit_progress("tactical_modules", "started", 92,
                          "Running tactical analysis...")
        log_pipeline_phase(self.analysis_id, "tactical_modules", "started")

        # HLZ finder and ponding detector will be implemented in Phase 3
        self.warnings.append("HLZ finder and ponding detector: detailed implementation pending")
        log_pipeline_phase(self.analysis_id, "tactical_modules", "completed")

        self.phase_timings["tactical_modules"] = time.monotonic() - phase_start
        self._emit_progress("tactical_modules", "completed", 95,
                          "Tactical analysis complete")

    # ─── Database Storage Methods ────────────────────────────

    def _create_analysis_record(self, db) -> None:
        """Create the master analysis record in the database."""
        db.execute(
            """
            INSERT INTO analyses (id, aoi_bbox, disaster_date, utm_zone, utm_epsg, status)
            VALUES (?, ?, ?, ?, ?, 'queued')
            """,
            [
                self.analysis_id,
                self.aoi.to_wkt(),
                self.disaster_date.isoformat(),
                self.aoi.utm_zone,
                self.utm_epsg,
            ],
        )

    def _update_status(self, db, status: str, progress: float, phase: str | None) -> None:
        """Update analysis status and progress in the database."""
        db.execute(
            "UPDATE analyses SET status=?, progress_pct=?, current_phase=? WHERE id=?",
            [status, progress, phase, self.analysis_id],
        )
        if status == "complete":
            db.execute(
                "UPDATE analyses SET completed_at=current_timestamp WHERE id=?",
                [self.analysis_id],
            )

    def _update_analysis_stats(self, db, stats: dict) -> None:
        """Update analysis with computed statistics."""
        db.execute(
            """
            UPDATE analyses SET
                flood_area_km2=?, roads_total_km=?, roads_severed_km=?,
                roads_partial_km=?, bridges_total=?, bridges_destroyed=?,
                bridges_damaged=?, buildings_total=?, buildings_submerged=?,
                buildings_contact=?, settlements_total=?, settlements_isolated=?,
                settlements_degraded=?, hlz_count=?, ponding_count=?
            WHERE id=?
            """,
            [
                stats.get("flood_area_km2"),
                stats.get("roads_total_km"),
                stats.get("roads_severed_km"),
                stats.get("roads_partial_km"),
                stats.get("bridges_total"),
                stats.get("bridges_destroyed"),
                stats.get("bridges_damaged"),
                stats.get("buildings_total"),
                stats.get("buildings_submerged"),
                stats.get("buildings_contact"),
                stats.get("settlements_total"),
                stats.get("settlements_isolated"),
                stats.get("settlements_degraded"),
                stats.get("hlz_count"),
                stats.get("ponding_count"),
                self.analysis_id,
            ],
        )

    def _store_flood_polygons(self, features: list[dict]) -> None:
        """Store flood polygons in the database."""
        db = get_db()
        for feat in features:
            props = feat["properties"]
            from shapely.geometry import shape
            geom = shape(feat["geometry"])
            db.execute(
                """
                INSERT INTO flood_polygons (id, analysis_id, geom_wkt, area_m2, confidence, detection_method)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    props["id"], self.analysis_id, geom.wkt,
                    props["area_m2"], props.get("confidence"),
                    "ensemble",
                ],
            )
        logger.info("Stored %d flood polygons in database", len(features))

    def _store_roads(self, roads_gdf: gpd.GeoDataFrame) -> None:
        """Store classified road segments in the database."""
        if roads_gdf.empty:
            return
        db = get_db()
        for idx, road in roads_gdf.iterrows():
            db.execute(
                """
                INSERT INTO road_segments
                    (id, analysis_id, osm_id, geom_wkt, highway_type, name,
                     length_m, damage_class, flood_intersection_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()), self.analysis_id,
                    road.get("osm_id"), road.geometry.wkt,
                    road.get("highway", road.get("highway_type")),
                    road.get("name"), road.get("length_m", road.geometry.length),
                    road.get("damage_class", "intact"),
                    road.get("flood_intersection_ratio", 0.0),
                ],
            )
        logger.info("Stored %d road segments", len(roads_gdf))

    def _store_bridges(self, bridges_gdf: gpd.GeoDataFrame) -> None:
        """Store classified bridges in the database."""
        if bridges_gdf.empty:
            return
        db = get_db()
        for idx, bridge in bridges_gdf.iterrows():
            db.execute(
                """
                INSERT INTO bridges (id, analysis_id, osm_id, geom_wkt, name,
                                     damage_class, buffer_flood_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()), self.analysis_id,
                    bridge.get("osm_id"), bridge.geometry.wkt,
                    bridge.get("name"), bridge.get("damage_class", "intact"),
                    bridge.get("buffer_flood_ratio", 0.0),
                ],
            )
        logger.info("Stored %d bridges", len(bridges_gdf))

    def _store_buildings(self, buildings_gdf: gpd.GeoDataFrame) -> None:
        """Store classified buildings in the database."""
        if buildings_gdf.empty:
            return
        db = get_db()
        for idx, bldg in buildings_gdf.iterrows():
            db.execute(
                """
                INSERT INTO buildings (id, analysis_id, osm_id, geom_wkt,
                                       building_type, damage_class, flood_intersection_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()), self.analysis_id,
                    bldg.get("osm_id"), bldg.geometry.wkt,
                    bldg.get("building"), bldg.get("damage_class", "safe"),
                    bldg.get("flood_intersection_ratio", 0.0),
                ],
            )
        logger.info("Stored %d buildings", len(buildings_gdf))

    def _store_settlements(self, settlements_gdf: gpd.GeoDataFrame) -> None:
        """Store scored settlements in the database."""
        if settlements_gdf.empty:
            return
        db = get_db()
        for idx, s in settlements_gdf.iterrows():
            db.execute(
                """
                INSERT INTO settlements
                    (id, analysis_id, osm_id, geom_wkt, name, place_type,
                     estimated_population, isolation_status, urgency_score,
                     pre_disaster_hub_dist_m, post_disaster_hub_dist_m, has_clinic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    s.get("id", str(uuid.uuid4())), self.analysis_id,
                    s.get("osm_id"), s.geometry.wkt,
                    s.get("name"), s.get("place", s.get("place_type")),
                    s.get("estimated_population"),
                    s.get("isolation_status", "connected"),
                    s.get("urgency_score", 0.0),
                    s.get("pre_disaster_hub_dist_m"),
                    s.get("post_disaster_hub_dist_m"),
                    s.get("has_clinic", False),
                ],
            )
        logger.info("Stored %d settlements", len(settlements_gdf))

    def _store_hubs(self, hubs_gdf: gpd.GeoDataFrame) -> None:
        """Store hub nodes in the database."""
        if hubs_gdf.empty:
            return
        db = get_db()
        for idx, hub in hubs_gdf.iterrows():
            db.execute(
                """
                INSERT INTO hub_nodes (id, analysis_id, osm_id, geom_wkt, name,
                                       hub_type, amenity_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    hub.get("id", str(uuid.uuid4())), self.analysis_id,
                    hub.get("osm_id"), hub.geometry.wkt,
                    hub.get("name"), "healthcare",
                    hub.get("amenity"),
                ],
            )
        logger.info("Stored %d hub nodes", len(hubs_gdf))

    # ─── Helpers ─────────────────────────────────────────────

    def _emit_progress(
        self, phase: str, status: str, pct: float, message: str
    ) -> None:
        """Emit a progress update via callback."""
        if self.progress_callback:
            self.progress_callback({
                "type": "progress",
                "analysis_id": self.analysis_id,
                "phase": phase,
                "status": status,
                "progress_pct": pct,
                "message": message,
            })

    @staticmethod
    def _features_to_geodataframe(
        features: list[dict], crs
    ) -> gpd.GeoDataFrame:
        """Convert GeoJSON features to a GeoDataFrame."""
        from shapely.geometry import shape

        if not features:
            return gpd.GeoDataFrame(columns=["geometry"], crs=crs)

        geometries = []
        properties = []
        for feat in features:
            geometries.append(shape(feat["geometry"]))
            properties.append(feat["properties"])

        import pandas as pd
        gdf = gpd.GeoDataFrame(
            pd.DataFrame(properties),
            geometry=geometries,
            crs=crs,
        )
        return gdf


# ─── Entry Point ─────────────────────────────────────────────

def run_pipeline(
    request: AnalysisRequest,
    analysis_id: str | None = None,
    progress_callback: callable | None = None,
) -> dict[str, Any]:
    """
    Run the full S.T.R.A.N.D analysis pipeline.

    Args:
        request: Validated AnalysisRequest with AOI, date, and options.
        analysis_id: Optional analysis ID (auto-generated if None).
        progress_callback: Optional function to receive progress updates.

    Returns:
        Result dict with analysis_id, status, summary, and warnings.
    """
    if analysis_id is None:
        analysis_id = str(uuid.uuid4())

    orchestrator = PipelineOrchestrator(
        analysis_id=analysis_id,
        request=request,
        progress_callback=progress_callback,
    )

    return orchestrator.run()
