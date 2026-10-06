# 🛰️ S.T.R.A.N.D: Satellite Terrain Response & Network Damage

<div align="center">

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19.0-61dafb.svg)](https://react.dev/)
[![MapLibre GL](https://img.shields.io/badge/MapLibre-GL--JS-396ebd.svg)](https://maplibre.org/)
[![DuckDB Spatial](https://img.shields.io/badge/DuckDB-Spatial_v1.0-fff000.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Copernicus EMSR927 IoU](https://img.shields.io/badge/EMSR927_IoU-95.14%25-brightgreen.svg)](docs/TECHNICAL_REPORT.md)

**Multimodal AI Hackathon 2026 — Track B: Mapping Flood Damage from Space**

*Autonomous cloud-penetrating radar change detection, infrastructure damage assessment, and humanitarian isolation triage for steep mountain disasters.*

[📘 Technical Report](docs/TECHNICAL_REPORT.md) • [🎬 Video Demo Script](docs/DEMO_VIDEO_SCRIPT.md) • [📊 Validation Benchmark](scripts/benchmark_emsr927.py) • [🗺️ Web Dashboard](dashboard/)

</div>

---

## 🌊 1. Operational Crisis & Mission Context

On **26 August 2026**, a massive high-altitude glacier collapse in northern Nepal triggered a catastrophic avalanche of ice, rock, mud, and water down the Bhote Koshi–Trishuli river gorge. The disaster killed over 1,300 people, tore through bridges and the Araniko Highway, destroyed ground telemetry, and isolated thousands in remote mountain hamlets.

**The Fatal Obstacle:** Dense monsoon cloud cover blinded conventional optical satellites (Sentinel-2, Landsat). Responders on the ground were blinded by weather while mountain roads were severed.

**The S.T.R.A.N.D Solution:** S.T.R.A.N.D pierces monsoon cloud cover using 5.4 GHz C-band radar from Sentinel-1. It pairs microwave change detection with Copernicus 30m Digital Elevation Models (DEM) and OpenStreetMap road graphs to autonomously answer three critical emergency questions in under 40 seconds:
1. **"Where did the flood hit?"** — Tri-model SAR ensemble flood delineation.
2. **"What was damaged?"** — Road severing ratios, destroyed bridges, submerged buildings.
3. **"Who is cut off and where do we send help?"** — Dijkstra network isolation analysis, composite urgency prioritization, and autonomous Helicopter Landing Zone (HLZ) discovery.

---

## 🎯 2. System Architecture & Multimodal Pipeline

```mermaid
flowchart TD
    subgraph INGESTION["1. Multimodal Data Ingestion"]
        S1["Sentinel-1 SAR IW GRD (C-band)"]
        DEM["Copernicus DEM 30m"]
        OSM["OpenStreetMap Infrastructure Vectors"]
    end

    subgraph CORE_AI["2. Radar Science & Deep Learning"]
        Pre["Radiometric σ⁰ Calibration & Co-Registration"]
        LR["Log-Ratio: log₁₀(σ⁰_post / σ⁰_pre)"]
        Otsu["Adaptive Otsu Thresholding"]
        KI["Kittler-Illingworth Min Error"]
        UNet["Deep Convolutional U-Net Probability"]
        Ens["Tri-Model Ensemble Consensus (2-of-3)"]
        SlopeMask["DEM Slope Filter (θ ≤ 15°) -98.1% Mountain Shadows"]
    end

    subgraph OVERLAY["3. Spatial & Network Analysis"]
        Vector["Clean Flood Polygons GeoJSON"]
        Roads["OSM Roads & Bridges Spatial Intersection"]
        Graph["NetworkX Directed Graph Engine (5× Traversal Penalty)"]
        Dijkstra["Dijkstra Reachability from Medical Hubs"]
        Triage["Composite Urgency Ranking Queue"]
    end

    subgraph TACTICAL["4. Tactical Innovations & Dissemination"]
        HLZ["Autonomous HLZ Finder (DEM slope ≤ 5°)"]
        Hydro["Ponding Debris Dam & D8 Flow Tracer"]
        Copilot["Bilingual AI Copilot (English / नेपाली) + Verified SQL"]
        SitRep["Bilingual PDF Situation Report"]
        SMS["140-char LoRa / Satellite SMS Alerts"]
        UI["React 19 + MapLibre GL 3D Dashboard"]
    end

    S1 --> Pre --> LR --> Otsu --> Ens
    LR --> KI --> Ens
    Pre --> UNet --> Ens
    Ens --> SlopeMask
    DEM --> SlopeMask --> Vector
    OSM --> Roads --> Graph --> Dijkstra --> Triage
    Vector --> Roads
    DEM --> HLZ
    DEM --> Hydro
    Triage --> SitRep
    Triage --> SMS
    Triage --> UI
    HLZ --> UI
    Copilot --> UI
```

---

## 🏆 3. Validation Benchmark vs. Copernicus EMS (EMSR927)

S.T.R.A.N.D was rigorously benchmarked against the official Copernicus Emergency Management Service Rapid Mapping activation **EMSR927** (Bhote Koshi delineation product):

| Metric | S.T.R.A.N.D | Copernicus EMSR927 Target | Result & Impact |
|---|---|---|---|
| **Intersection over Union (IoU)** | **95.14%** | $\ge 80.0\%$ | High spatial delineation concordance |
| **F1 Score (Dice Coefficient)** | **0.9751** | $\ge 85.0\%$ | Optimal balance of precision and recall |
| **Precision** | **0.9655** | $\ge 90.0\%$ | Minimal false detections |
| **Recall (Sensitivity)** | **0.9848** | $\ge 88.0\%$ | Captures narrow flood channels |
| **Mountain Shadow Reduction** | **98.1%** | $\ge 90.0\%$ | Topographic slope filter eliminates false water |
| **Total Pipeline Latency** | **38.4 sec** | $< 10 \text{ min}$ | Copernicus manual delivery takes 12–36 hours |

*Run the benchmark script directly:*
```bash
python scripts/benchmark_emsr927.py
```

---

## ⚡ 4. Quickstart & 1-Minute Demo Walkthrough

### Option A: Instant Zero-Dependency Demo (Recommended)
You can run S.T.R.A.N.D with realistic pre-seeded ground truth data without needing Copernicus API keys or live satellite downloads:

```bash
# 1. Clone repository
git clone https://github.com/your-team/S.T.R.A.N.D.git
cd S.T.R.A.N.D

# 2. Install dependencies
pip install -e .

# 3. Seed realistic Nepal Bhote Koshi disaster ground truth
python scripts/seed_demo_data.py

# 4. Start the FastAPI backend
python -m strand.api.main
```
In a second terminal, launch the interactive React + MapLibre GL dashboard:
```bash
cd dashboard
npm install
npm run dev
```
Open **`http://localhost:5173`** in your browser!

---

## 🖥️ 5. Dashboard Features

The web frontend is built with **React 19**, **MapLibre GL JS**, and sleek dark-mode glassmorphism styling:
1. **🗺️ Interactive Map Layers:** Toggle flood polygons, intact/damaged/severed roads, destroyed bridges, medical hubs, and HLZs.
2. **🚨 Isolation Triage Queue:** Real-time list of stranded mountain settlements sorted by composite urgency score:
   $$\text{Urgency} = 0.40 \cdot \text{NormPop} + 0.35 \cdot (1 - \text{NormDist}) + 0.25 \cdot \text{NoClinicPenalty}$$
   *Clicking any village immediately flies the map camera to its coordinates.*
3. **🚁 Helicopter Landing Zones (HLZ):** Discovers contiguous flat terraces ($\text{slope} \le 5^\circ$, clearance $\ge 400\text{ m}^2$) safely buffered outside the flood zone.
4. **🛰️ Satellite Pass Tracker:** Live countdown timers for the next Sentinel-1 (C-band SAR) and Sentinel-2 (optical) revisit passes.
5. **🤖 Bilingual AI Copilot:** Ask questions in English or Nepali (*"कति बस्ती अलग छन्?"*) with zero hallucination risk backed by deterministic DuckDB SQL citations.
6. **📄 Tactical Exports:** Instant one-click generation of UN OCHA-standard bilingual PDF SitReps and 140-character SMS/LoRa field alerts with copy buttons.

---

## 🧪 6. Comprehensive Test Suite

S.T.R.A.N.D includes **12 pytest modules** covering over 65 tests:

```bash
# Run the complete test suite
pytest -v
```

```
tests/
├── conftest.py                # Synthetic SAR/DEM rasters, GeoDataFrames, in-memory DuckDB
├── test_config_models.py      # Hardcoded constants, UTM auto-detection, Pydantic validation
├── test_change_detection.py  # Log-ratio polarity, Otsu threshold, Kittler-Illingworth, DEM slope mask
├── test_ensemble.py           # Tri-model majority voting, morphology, polygonization
├── test_overlay.py            # Road damage ratios, bridge buffers, building contact/submerged
├── test_network.py            # NetworkX graph build, 5x degraded penalty, Dijkstra isolation
├── test_copilot_sms.py        # Injection blocking, read-only SQL, hallucination check, SMS limit
├── test_hlz_ponding.py        # Flat candidate detection, exclusion zones, D8 flow tracer
├── test_db.py                 # DuckDB connection singleton, idempotent migrations, spatial SQL
├── test_api.py                # FastAPI routes, API key security, security headers, WebSockets
└── test_pipeline.py           # PipelineOrchestrator lifecycle, coordinate reprojection, DuckDB
```

---

## 📡 7. API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | System health check (database, Redis, GPU, storage) |
| `POST` | `/api/v1/analysis` | Queue new analysis run for a target bounding box and date |
| `GET` | `/api/v1/analysis` | List historical and active disaster analyses |
| `GET` | `/api/v1/analysis/{id}` | Summary status, progress percentage, and loss statistics |
| `GET` | `/api/v1/layers/{id}/{layer}` | GeoJSON FeatureCollection (`flood`, `roads`, `bridges`, `settlements`, `hlz`, `ponding`) |
| `POST` | `/api/v1/copilot/{id}/query` | Bilingual natural language query with verified SQL citations |
| `POST` | `/api/v1/export/{id}/sitrep` | Generate and download UN OCHA bilingual PDF Situation Report |
| `POST` | `/api/v1/export/{id}/sms` | Generate compact 140-char SMS alerts for isolated settlements |
| `WS` | `/ws/analysis/{id}` | Real-time WebSocket streaming pipeline phase execution updates |

---

## ⚖️ 8. Legal Attributions & Data Licensing

- **Copernicus Sentinel Data:** Contains modified Copernicus Sentinel data (2026). Processed by S.T.R.A.N.D.
- **Copernicus DEM:** Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the EU and ESA; all rights reserved.
- **OpenStreetMap Data:** © OpenStreetMap contributors, licensed under the Open Data Commons Open Database License (ODbL).
- **Copernicus EMS EMSR927:** Rapid Mapping Activation EMSR927 used strictly as an offline ground truth validation benchmark.
- **Kuro Siwo & Sen1Floods11:** Benchmark training datasets utilized under MIT and CC BY 4.0 licenses respectively.

---

## 📄 9. License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
