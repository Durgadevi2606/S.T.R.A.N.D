#!/usr/bin/env python3
"""
S.T.R.A.N.D — Seed Realistic Nepal Disaster Demo Data

Populates DuckDB with high-fidelity, realistic data for the
August 26, 2026 Bhote Koshi - Trishuli glacial collapse disaster.

This enables immediate end-to-end testing and rich visualization
on the dashboard, triage panel, copilot, and PDF SitRep exports.

Usage:
    python scripts/seed_demo_data.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from strand.config import get_settings
from strand.db.connection import close_db, get_db
from strand.db.migrations import run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEMO_ANALYSIS_ID = "nepal-bhotekoshi-20260826"


def seed_demo_data() -> None:
    """Insert comprehensive Bhote Koshi disaster dataset."""
    logger.info("Initializing database schema...")
    run_migrations()
    conn = get_db()

    logger.info("Seeding demo analysis record [%s]...", DEMO_ANALYSIS_ID)

    # 1. Analyses Master Record
    conn.execute(
        """
        INSERT OR REPLACE INTO analyses (
            id, aoi_bbox, disaster_date, utm_zone, utm_epsg,
            s1_orbit_number, sar_pre_product, sar_post_product,
            sar_pre_date, sar_post_date, orbit_direction,
            dem_product, s2_product, s2_available,
            osm_snapshot_ts, status, progress_pct, current_phase,
            flood_area_km2, roads_total_km, roads_severed_km, roads_partial_km,
            bridges_total, bridges_destroyed, bridges_damaged,
            buildings_total, buildings_submerged, buildings_contact,
            settlements_total, settlements_isolated, settlements_degraded,
            hlz_count, ponding_count, created_at, completed_at
        ) VALUES (
            ?, '85.85,27.75,86.00,28.00', '2026-08-26', 45, 32645,
            121, 'S1A_IW_GRDH_1SDV_20260820T001520', 'S1A_IW_GRDH_1SDV_20260826T123015',
            '2026-08-20', '2026-08-26', 'DESCENDING',
            'COP-DEM-GLO-30', 'S2A_MSIL2A_20260826T045000', TRUE,
            '2026-08-26T00:00:00Z', 'complete', 100.0, 'completed',
            14.85, 84.6, 21.4, 12.8,
            8, 4, 2,
            1420, 312, 185,
            12, 5, 3,
            6, 2, ?, ?
        )
        """,
        [
            DEMO_ANALYSIS_ID,
            datetime(2026, 8, 26, 14, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 26, 14, 25, 0, tzinfo=timezone.utc),
        ],
    )

    # Clear previous child rows for idempotency
    tables = [
        "flood_polygons",
        "road_segments",
        "bridges",
        "buildings",
        "settlements",
        "hub_nodes",
        "hlz_sites",
        "ponding_zones",
        "pipeline_logs",
    ]
    for tbl in tables:
        conn.execute(f"DELETE FROM {tbl} WHERE analysis_id = ?", [DEMO_ANALYSIS_ID])

    logger.info("Inserting flood extent polygons...")
    # 2. Flood Polygons (along Bhote Koshi river corridor)
    flood_features = [
        (
            f"{DEMO_ANALYSIS_ID}-f1",
            "POLYGON((85.900 27.850, 85.908 27.865, 85.925 27.900, 85.932 27.930, 85.928 27.935, 85.918 27.905, 85.902 27.870, 85.895 27.852, 85.900 27.850))",
            6800000.0,
            0.92,
            "ensemble_majority",
            True,
        ),
        (
            f"{DEMO_ANALYSIS_ID}-f2",
            "POLYGON((85.932 27.930, 85.945 27.960, 85.952 27.985, 85.946 27.990, 85.938 27.962, 85.926 27.933, 85.932 27.930))",
            5200000.0,
            0.88,
            "ensemble_majority",
            False,
        ),
        (
            f"{DEMO_ANALYSIS_ID}-f3",
            "POLYGON((85.885 27.800, 85.892 27.825, 85.900 27.850, 85.895 27.852, 85.886 27.828, 85.880 27.802, 85.885 27.800))",
            2850000.0,
            0.84,
            "otsu_sar",
            True,
        ),
    ]
    for fid, geom, area, conf, meth, mndwi in flood_features:
        conn.execute(
            """
            INSERT INTO flood_polygons (id, analysis_id, geom_wkt, area_m2, confidence, detection_method, mndwi_validated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [fid, DEMO_ANALYSIS_ID, geom, area, conf, meth, mndwi],
        )

    logger.info("Inserting road network segments...")
    # 3. Road Segments (Araniko Highway corridor & feeder roads)
    roads = [
        ("r1", 101, "LINESTRING(85.875 27.780, 85.885 27.805)", "primary", "Araniko Highway Sec 1", 3200.0, "intact", 0.0),
        ("r2", 102, "LINESTRING(85.885 27.805, 85.895 27.835)", "primary", "Araniko Highway Sec 2", 3600.0, "partially_flooded", 0.35),
        ("r3", 103, "LINESTRING(85.895 27.835, 85.908 27.868)", "primary", "Araniko Highway (Barhabise Gorge)", 4100.0, "severed", 0.85),
        ("r4", 104, "LINESTRING(85.908 27.868, 85.922 27.898)", "primary", "Araniko Highway (Chaku Pass)", 3900.0, "severed", 0.78),
        ("r5", 105, "LINESTRING(85.922 27.898, 85.935 27.935)", "primary", "Araniko Highway (Tatopani Approach)", 4500.0, "severed", 0.92),
        ("r6", 106, "LINESTRING(85.935 27.935, 85.950 27.980)", "primary", "Araniko Highway (Kodari Border)", 5200.0, "severed", 0.95),
        ("r7", 107, "LINESTRING(85.885 27.805, 85.870 27.830)", "secondary", "Maneshwara Link Road", 3100.0, "intact", 0.0),
        ("r8", 108, "LINESTRING(85.908 27.868, 85.930 27.875)", "tertiary", "Marming Ridge Track", 2600.0, "partially_flooded", 0.22),
    ]
    for rid, osmid, geom, hwy, name, length, dmg, ratio in roads:
        conn.execute(
            """
            INSERT INTO road_segments (id, analysis_id, osm_id, geom_wkt, highway_type, name, length_m, damage_class, flood_intersection_ratio, is_graph_edge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            """,
            [f"{DEMO_ANALYSIS_ID}-{rid}", DEMO_ANALYSIS_ID, osmid, geom, hwy, name, length, dmg, ratio],
        )

    logger.info("Inserting bridges...")
    # 4. Bridges
    bridges = [
        ("b1", 201, "POINT(85.895 27.835)", "Barhabise Main Bridge", "damaged", 0.45),
        ("b2", 202, "POINT(85.908 27.868)", "Larcha Suspension Bridge", "destroyed", 1.00),
        ("b3", 203, "POINT(85.922 27.898)", "Chaku Khola Concrete Bridge", "destroyed", 0.95),
        ("b4", 204, "POINT(85.935 27.935)", "Tatopani Friendship Bridge", "destroyed", 1.00),
        ("b5", 205, "POINT(85.945 27.970)", "Lipingle Bridge", "destroyed", 0.88),
        ("b6", 206, "POINT(85.875 27.780)", "Balephi Crossing", "intact", 0.00),
        ("b7", 207, "POINT(85.870 27.830)", "Maneshwara Footbridge", "intact", 0.00),
        ("b8", 208, "POINT(85.930 27.875)", "Marming Stream Bridge", "damaged", 0.30),
    ]
    for bid, osmid, geom, name, dmg, ratio in bridges:
        conn.execute(
            """
            INSERT INTO bridges (id, analysis_id, osm_id, geom_wkt, name, damage_class, buffer_flood_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [f"{DEMO_ANALYSIS_ID}-{bid}", DEMO_ANALYSIS_ID, osmid, geom, name, dmg, ratio],
        )

    logger.info("Inserting settlements & isolation triage status...")
    # 5. Settlements
    settlements = [
        ("s1", 301, "POINT(85.900 27.840)", "Barhabise Bazar", "town", 5200, "degraded", 0.68, 1200.0, 3600.0, True, "hlz-1"),
        ("s2", 302, "POINT(85.935 27.940)", "Tatopani", "village", 1850, "isolated", 0.96, 14500.0, -1.0, False, "hlz-2"),
        ("s3", 303, "POINT(85.948 27.975)", "Kodari", "village", 940, "isolated", 0.92, 19200.0, -1.0, False, "hlz-3"),
        ("s4", 304, "POINT(85.952 27.990)", "Liping", "hamlet", 420, "isolated", 0.89, 21500.0, -1.0, False, "hlz-3"),
        ("s5", 305, "POINT(85.915 27.880)", "Chaku", "village", 780, "isolated", 0.85, 8200.0, -1.0, False, "hlz-4"),
        ("s6", 306, "POINT(85.925 27.910)", "Hindi", "village", 650, "isolated", 0.81, 11400.0, -1.0, False, "hlz-2"),
        ("s7", 307, "POINT(85.875 27.790)", "Balephi", "town", 4100, "connected", 0.05, 500.0, 500.0, True, "hlz-5"),
        ("s8", 308, "POINT(85.865 27.820)", "Maneshwara", "village", 1200, "connected", 0.12, 3400.0, 3400.0, False, "hlz-6"),
    ]
    for sid, osmid, geom, name, ptype, pop, status, urg, pre_d, post_d, clinic, hlz in settlements:
        conn.execute(
            """
            INSERT INTO settlements (
                id, analysis_id, osm_id, geom_wkt, name, place_type,
                estimated_population, isolation_status, urgency_score,
                pre_disaster_hub_dist_m, post_disaster_hub_dist_m,
                has_clinic, nearest_hlz_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"{DEMO_ANALYSIS_ID}-{sid}",
                DEMO_ANALYSIS_ID,
                osmid,
                geom,
                name,
                ptype,
                pop,
                status,
                urg,
                pre_d,
                post_d,
                clinic,
                f"{DEMO_ANALYSIS_ID}-{hlz}",
            ],
        )

    logger.info("Inserting medical hubs...")
    # 6. Hub Nodes
    hubs = [
        ("h1", 401, "POINT(85.872 27.785)", "Balephi Regional Health Post", "medical", "hospital"),
        ("h2", 402, "POINT(85.898 27.838)", "Barhabise Primary Health Centre", "medical", "clinic"),
    ]
    for hid, osmid, geom, name, htype, atype in hubs:
        conn.execute(
            """
            INSERT INTO hub_nodes (id, analysis_id, osm_id, geom_wkt, name, hub_type, amenity_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [f"{DEMO_ANALYSIS_ID}-{hid}", DEMO_ANALYSIS_ID, osmid, geom, name, htype, atype],
        )

    logger.info("Inserting helicopter landing zones (HLZ)...")
    # 7. HLZ Sites
    hlzs = [
        ("hlz-1", "POLYGON((85.892 27.845, 85.895 27.845, 85.895 27.842, 85.892 27.842, 85.892 27.845))", "POINT(85.8935 27.8435)", 1850.0, 2.1, 3.8, 1150.0, f"{DEMO_ANALYSIS_ID}-s1", 620.0, "gravel_terrace"),
        ("hlz-2", "POLYGON((85.928 27.925, 85.932 27.925, 85.932 27.922, 85.928 27.922, 85.928 27.925))", "POINT(85.9300 27.9235)", 2100.0, 2.8, 4.2, 1680.0, f"{DEMO_ANALYSIS_ID}-s2", 950.0, "school_ground"),
        ("hlz-3", "POLYGON((85.942 27.965, 85.946 27.965, 85.946 27.962, 85.942 27.962, 85.942 27.965))", "POINT(85.9440 27.9635)", 1420.0, 3.2, 4.8, 2120.0, f"{DEMO_ANALYSIS_ID}-s3", 840.0, "customs_helipad"),
        ("hlz-4", "POLYGON((85.912 27.872, 85.915 27.872, 85.915 27.869, 85.912 27.869, 85.912 27.872))", "POINT(85.9135 27.8705)", 1600.0, 1.9, 3.4, 1380.0, f"{DEMO_ANALYSIS_ID}-s5", 480.0, "flat_ridge"),
        ("hlz-5", "POLYGON((85.878 27.795, 85.882 27.795, 85.882 27.792, 85.878 27.792, 85.878 27.795))", "POINT(85.8800 27.7935)", 3200.0, 1.2, 2.1, 890.0, f"{DEMO_ANALYSIS_ID}-s7", 510.0, "river_terrace"),
        ("hlz-6", "POLYGON((85.862 27.825, 85.866 27.825, 85.866 27.822, 85.862 27.822, 85.862 27.825))", "POINT(85.8640 27.8235)", 1950.0, 2.4, 3.9, 1420.0, f"{DEMO_ANALYSIS_ID}-s8", 730.0, "field_plateau"),
    ]
    for hzid, poly_wkt, cent_wkt, area, avg_sl, max_sl, elev, s_id, dist, surf in hlzs:
        conn.execute(
            """
            INSERT INTO hlz_sites (
                id, analysis_id, geom_wkt, centroid_wkt, area_m2,
                avg_slope_deg, max_slope_deg, elevation_m,
                nearest_settlement_id, dist_to_settlement_m, surface_estimate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"{DEMO_ANALYSIS_ID}-{hzid}",
                DEMO_ANALYSIS_ID,
                poly_wkt,
                cent_wkt,
                area,
                avg_sl,
                max_sl,
                elev,
                s_id,
                dist,
                surf,
            ],
        )

    logger.info("Inserting ponding hazard zones...")
    # 8. Ponding Zones
    ponding = [
        ("pz-1", "POLYGON((85.918 27.892, 85.924 27.892, 85.924 27.888, 85.918 27.888, 85.918 27.892))", 125000.0, 850000.0, 1420.0, "critical"),
        ("pz-2", "POLYGON((85.938 27.952, 85.944 27.952, 85.944 27.948, 85.938 27.948, 85.938 27.952))", 78000.0, 420000.0, 1890.0, "high"),
    ]
    for pzid, gwkt, area, vol, dam_el, risk in ponding:
        conn.execute(
            """
            INSERT INTO ponding_zones (id, analysis_id, geom_wkt, area_m2, estimated_volume_m3, dam_elevation_m, risk_level)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [f"{DEMO_ANALYSIS_ID}-{pzid}", DEMO_ANALYSIS_ID, gwkt, area, vol, dam_el, risk],
        )

    logger.info("Inserting pipeline execution logs...")
    # 9. Pipeline Logs
    logs = [
        ("l1", "aoi_validation", "completed", "AOI validated: 85.85 to 86.00 E, 27.75 to 28.00 N (245.8 km²)", 10.0),
        ("l2", "cdse_discovery", "completed", "SAR pair discovered: pre=2026-08-20, post=2026-08-26", 25.0),
        ("l3", "sar_preprocessing", "completed", "Radiometric calibration & Range-Doppler terrain correction finished", 45.0),
        ("l4", "change_detection", "completed", "Log-ratio & Otsu thresholding completed. Slope masking eliminated 12.4% false positives.", 60.0),
        ("l5", "ensemble_segmentation", "completed", "Multi-model ensemble reached consensus. 14.85 km² flood polygons vectorized.", 75.0),
        ("l6", "infrastructure_overlay", "completed", "OSM overlay: 21.4km severed roads, 4 destroyed bridges, 312 submerged buildings.", 85.0),
        ("l7", "network_reachability", "completed", "Dijkstra analysis: 5 settlements isolated (Tatopani, Kodari, Liping, Chaku, Hindi).", 95.0),
        ("l8", "tactical_modules", "completed", "6 safe HLZ sites identified. 2 critical ponding zones detected.", 100.0),
    ]
    for lid, phase, status, msg, pct in logs:
        conn.execute(
            """
            INSERT INTO pipeline_logs (id, analysis_id, phase, status, message, progress_pct)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [f"{DEMO_ANALYSIS_ID}-{lid}", DEMO_ANALYSIS_ID, phase, status, msg, pct],
        )

    logger.info("✅ Demo dataset seeded successfully into DuckDB!")
    close_db()


if __name__ == "__main__":
    seed_demo_data()
