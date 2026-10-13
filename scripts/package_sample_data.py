import os
import json
import shutil
import zipfile
import pathlib
import urllib.request

API_BASE = "http://127.0.0.1:8000/api/v1"
API_KEY = "dev-key-change-in-production"
ANALYSIS_ID = "sar-import-20261007-6a83b3"

DOWNLOADS_DIR = pathlib.Path(r"C:\Users\Durga\Downloads")
SAMPLE_FOLDER = DOWNLOADS_DIR / "STRAND_Sample_Data"
SAMPLE_ZIP = DOWNLOADS_DIR / "STRAND_Sample_Disaster_Dataset_Nepal_BhoteKoshi.zip"
PUBLIC_DEMO_DIR = pathlib.Path("dashboard/public/demo")

def fetch_json(endpoint):
    url = f"{API_BASE}/{endpoint}"
    req = urllib.request.Request(url, headers={"X-API-Key": API_KEY})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("Fetching active analysis data for:", ANALYSIS_ID)
    detail = fetch_json(f"analysis/{ANALYSIS_ID}")
    
    layers = {}
    for layer in ["flood", "roads", "bridges", "settlements", "hlz", "ponding"]:
        layers[layer] = fetch_json(f"layers/{ANALYSIS_ID}/{layer}")
        print(f"Fetched {layer}: {len(layers[layer].get('features', []))} features")

    # Create temporary staging directory for packaging
    staging_dir = pathlib.Path("data/sample_export_staging")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # 1. GeoJSON layers
    with open(staging_dir / "flood_inundation_polygons.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["flood"], f, indent=2)
    with open(staging_dir / "cut_off_roads.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["roads"], f, indent=2)
    with open(staging_dir / "damaged_bridges.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["bridges"], f, indent=2)
    with open(staging_dir / "isolated_settlements_triage.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["settlements"], f, indent=2)
    with open(staging_dir / "helicopter_landing_zones_hlz.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["hlz"], f, indent=2)
    with open(staging_dir / "soil_ponding_zones.geojson", "w", encoding="utf-8") as f:
        json.dump(layers["ponding"], f, indent=2)

    # 2. Damage Assessment SitRep Summary JSON
    summary = {
        "disaster_intelligence_system": "S.T.R.A.N.D PROD",
        "analysis_id": ANALYSIS_ID,
        "disaster_theater": "Bhote Koshi River Basin & Araniko Highway Corridor, Nepal",
        "bounding_box": [85.80, 27.70, 86.05, 28.05],
        "satellite_platform": "Sentinel-1 IW Mode (C-Band Synthetic Aperture Radar)",
        "norad_sync_timestamp": detail.get("created_at"),
        "tactical_metrics": {
            "flood_inundation_km2": detail.get("flood_area_km2", 178.56),
            "severed_roads_km": detail.get("roads_severed_km", 26.6),
            "damaged_bridges_count": detail.get("bridges_destroyed", 1),
            "isolated_settlements_count": detail.get("settlements_isolated", 2),
            "viable_hlz_sites_count": len(layers["hlz"].get("features", [])),
        },
        "details": detail
    }
    with open(staging_dir / "disaster_assessment_sitrep.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # 3. Sample SAR Radar Image for upload testing
    radar_img_src = pathlib.Path("data/raw/uploads/sar-import-20261007-6a83b3_radar_test.png")
    if radar_img_src.exists():
        shutil.copy(radar_img_src, staging_dir / "sample_sar_radar_imagery.png")
        print("Copied sample radar imagery into staging bundle.")

    # 4. README with instructions
    readme_content = """========================================================================
S.T.R.A.N.D - Satellite Tactical Reconnaissance & Autonomous Navigation in Disaster
SAMPLE DISASTER ASSESSMENT & RADAR DATASET
========================================================================

Disaster Theater: Bhote Koshi Basin / Araniko Highway Corridor, Nepal
Satellite Platform: Sentinel-1 IW C-Band SAR
Analysis ID: sar-import-20261007-6a83b3

INCLUDED ARTIFACTS:
------------------------------------------------------------------------
1. flood_inundation_polygons.geojson
   - GeoJSON polygons delineating the 178.56 km² flood inundation extent
   - Extracted from Otsu backscatter thresholding + speckle filtering

2. cut_off_roads.geojson
   - OSM Highway vector segments classified by disaster status:
     * severed (cut off by floodwaters)
     * partially_flooded (traversable with high delay penalty)
     * intact (operational bypass routes)

3. damaged_bridges.geojson
   - Bridge crossings tagged with damage status and flood buffer ratios

4. isolated_settlements_triage.geojson
   - Settlement nodes prioritized by composite urgency index
   - Includes population estimates, medical clinic availability, and cut-off status

5. helicopter_landing_zones_hlz.geojson
   - Flat terrain evacuation landing zones (slope <= 5°, rotor clearance >= 25m)

6. soil_ponding_zones.geojson
   - High-moisture silt saturation and secondary ponding areas

7. sample_sar_radar_imagery.png
   - Pre-calibrated SAR radar test imagery ready to upload directly into the
     S.T.R.A.N.D web dashboard via "UPLOAD SAR RADAR DATA"!

8. disaster_assessment_sitrep.json
   - Full JSON operational metrics and incident commander report

HOW TO USE:
------------------------------------------------------------------------
- Web Dashboard:
  Click "Upload SAR Radar Data" on the top right of http://localhost:5173
  and select `sample_sar_radar_imagery.png` to run real-time SAR ingestion!
- GIS Inspection:
  Open any of the GeoJSON files directly in QGIS, ArcGIS, or drag-and-drop
  them onto https://geojson.io to visualize the vectors.
========================================================================
"""
    with open(staging_dir / "README.txt", "w", encoding="utf-8") as f:
        f.write(readme_content)

    # 5. Create ZIP Archive
    print("Writing ZIP archive to:", SAMPLE_ZIP)
    with zipfile.ZipFile(SAMPLE_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in staging_dir.iterdir():
            zf.write(file, arcname=file.name)

    # 6. Also copy unzipped folder directly into Downloads for convenience
    if SAMPLE_FOLDER.exists():
        shutil.rmtree(SAMPLE_FOLDER)
    shutil.copytree(staging_dir, SAMPLE_FOLDER)
    print("Copied unzipped sample folder to:", SAMPLE_FOLDER)

    # 7. Copy to dashboard/public/demo for browser download button
    PUBLIC_DEMO_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE_ZIP, PUBLIC_DEMO_DIR / "STRAND_Sample_Disaster_Dataset_Nepal_BhoteKoshi.zip")
    
    # Also update demo json files so Vercel matches active dataset
    for layer_name, data in layers.items():
        with open(PUBLIC_DEMO_DIR / f"{layer_name}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    with open(PUBLIC_DEMO_DIR / "detail.json", "w", encoding="utf-8") as f:
        json.dump(detail, f, indent=2)

    print("Successfully packaged and downloaded sample data!")

if __name__ == "__main__":
    main()
