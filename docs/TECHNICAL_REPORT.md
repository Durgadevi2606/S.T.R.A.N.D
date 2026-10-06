# S.T.R.A.N.D: Satellite Terrain Response & Network Damage
## An Autonomous Multimodal Geospatial AI System for Cloud-Penetrating Flood Damage Mapping and Isolation Triage in Complex Mountainous Terrain

**Track B: Mapping Flood Damage from Space**  
*Multimodal AI Hackathon 2026*  

---

### Abstract
When catastrophic glacial lake outburst floods (GLOFs) and avalanche cascades strike high-altitude mountain corridors, ground sensors and cellular telemetry are rapidly obliterated. Simultaneously, monsoon cloud cover creates a persistent optical blind spot, rendering multispectral satellites ineffective. This paper presents **S.T.R.A.N.D** (Satellite Terrain Response & Network Damage), an end-to-end, autonomous multimodal AI platform engineered specifically for rapid post-disaster assessment in steep Himalayan topographies. 

S.T.R.A.N.D ingests Copernicus Sentinel-1 C-band Synthetic Aperture Radar (SAR) imagery, Copernicus 30m Digital Elevation Models (DEM), and OpenStreetMap (OSM) infrastructure graphs. By formulating a tri-model ensemble combining calibrated SAR log-ratio Otsu thresholding, Kittler-Illingworth minimum error estimation, and deep convolutional segmentation, S.T.R.A.N.D achieves an **Intersection over Union (IoU) of 95.14%** against the Copernicus Emergency Management Service (EMS) EMSR927 ground truth. Crucially, we introduce an integrated DEM slope filter ($\le 15^\circ$) that eliminates **98.1% of steep radar shadow false alarms** that plague conventional SAR methods. 

Beyond pixel-level flood mapping, S.T.R.A.N.D transforms raw inundation vectors into actionable humanitarian triage: it constructs directed road network graphs to detect severed corridors, isolates cut-off settlements via Dijkstra reachability, computes composite urgency rankings, discovers viable Helicopter Landing Zones (HLZ) on flat terraces ($\text{slope} \le 5^\circ$), and models secondary ponding debris dam risks. Operating in under 40 seconds end-to-end, S.T.R.A.N.D outputs publication-ready bilingual (English/Nepali) Situation Reports (SitReps) and 140-character satellite SMS alerts for frontline first responders.

---

## 1. Disaster Context & Problem Statement

On **26 August 2026**, a massive high-altitude glacier collapse in northern Nepal released over 10 million cubic meters of ice, rock, mud, and water down the Bhote Koshi–Trishuli river corridor. The event claimed more than 1,300 lives and isolated tens of thousands of residents across remote mountain valleys. Key transport lifelines—most notably the Araniko Highway connecting Kathmandu to the Tibetan border—were cut at multiple points by debris surges, swept bridges, and washed-out road embankments.

```
Glacier Collapse / Avalanche
           │
           ▼
Torrential Debris Flow (Bhote Koshi Corridor)
           │
 ┌─────────┴─────────┐
 ▼                   ▼
Ground Sensors    Monsoon Cloud Blind Spot
Destroyed         (Optical S2 Blended Out)
           │
           ▼
 FIRST RESPONDERS BLINDED
           │
           ▼
 [ S.T.R.A.N.D AI SYSTEM ]
 5.4 GHz C-Band Radar + DEM + Graph Triage
```

### The Three Critical Challenges
1. **The Optical Blind Spot:** During the Himalayan monsoon, cloud cover exceeds 85–95% for weeks at a time. Optical sensors (e.g., Sentinel-2 MSI, Landsat 9) capture only cloud tops. Responders cannot wait days for a cloud-free pass.
2. **Topographic Radar Distortion:** In steep mountain terrain, Synthetic Aperture Radar suffers severe geometric distortions: layover, foreshortening, and radar shadows. Areas in radar shadow exhibit near-zero backscatter, identically mimicking specular reflection from standing flood water and generating massive false positive rates.
3. **The "Water-Only" Actionability Gap:** Standard flood products output binary raster masks. Field commanders need immediate answers to structural questions: *Which bridges are down? Which villages have lost medical access? Where can an evacuation helicopter land right now?*

---

## 2. System Architecture & Multimodal Pipeline

S.T.R.A.N.D is architected as an asynchronous, containerized pipeline combining numerical radar science, deep learning, spatial database operations, and graph analytics.

```mermaid
flowchart TD
    S1[Sentinel-1 SAR IW GRD] --> Pre[Radiometric Calibration & Co-Registration]
    DEM[Copernicus DEM 30m] --> Slope[DEM Slope & Hillshade Engine]
    OSM[OpenStreetMap Ingestion] --> Graph[NetworkX Directed Road Graph]

    Pre --> CD[Log-Ratio Change Detection]
    Pre --> UNet[U-Net Probability Inference]
    CD --> Ens[Tri-Model Ensemble Voter]
    UNet --> Ens

    Ens --> TopoFilter[DEM Topographic Slope Filter]
    Slope --> TopoFilter
    TopoFilter --> Vector[Clean Flood Polygons GeoJSON]

    Vector --> Overlay[Infrastructure Overlay Engine]
    OSM --> Overlay
    Overlay --> Reach[Dijkstra Reachability Analysis]
    Graph --> Reach

    Reach --> Triage[Isolation Triage Queue]
    Slope --> HLZ[Helicopter Landing Zone Finder]
    DEM --> Hydro[D8 Flow & Ponding Hazard Engine]

    Triage --> SitRep[Bilingual PDF SitRep]
    Triage --> SMS[140-char SMS / LoRa Alerts]
    Triage --> Dashboard[MapLibre GL Interactive Dashboard]
```

---

## 3. SAR Change Detection & Topographic Noise Filtering

### 3.1 Radiometric Calibration & Log-Ratio Computation
Sentinel-1 Interferometric Wide (IW) Ground Range Detected (GRD) products are calibrated to linear backscatter coefficient $\sigma^0$:
$$\sigma^0 = \frac{DN^2}{A^2}$$
where $DN$ is digital number and $A$ is the calibration look-up table amplitude. 

Water surfaces act as specular reflectors, scattering radar microwaves away from the antenna and causing a steep drop in backscatter. Change detection between pre-event ($t_0$) and post-event ($t_1$) acquisitions is formulated via the logarithmic ratio:
$$R_{\text{VV}} = \log_{10}\left(\frac{\sigma^0_{t_1, \text{VV}} + \epsilon}{\sigma^0_{t_0, \text{VV}} + \epsilon}\right), \quad R_{\text{VH}} = \log_{10}\left(\frac{\sigma^0_{t_1, \text{VH}} + \epsilon}{\sigma^0_{t_0, \text{VH}} + \epsilon}\right)$$
where $\epsilon = 10^{-10}$ ensures numerical stability. Flood pixels satisfy $R < 0$.

### 3.2 Multi-Method Ensemble Consensus
To ensure high recall without sacrificing precision, S.T.R.A.N.D combines three distinct segmentation methodologies:
1. **Adaptive Otsu Thresholding:** Optimizes intraclass backscatter variance on $R_{\text{VV}}$.
2. **Kittler-Illingworth Minimum Error Thresholding:** Fits a two-component Gaussian mixture model to identify the non-change vs. inundation decision boundary:
   $$J(T) = 1 + 2\left[P_1(T)\ln \sigma_1(T) + P_2(T)\ln \sigma_2(T)\right] - 2\left[P_1(T)\ln P_1(T) + P_2(T)\ln P_2(T)\right]$$
3. **Deep Convolutional U-Net:** ResNet-34 encoder trained on Kuro Siwo and Sen1Floods11 multispectral/SAR paired datasets, producing continuous water probability maps $P_{\text{flood}}(x, y)$.

The ensemble decision rule enforces consensus:
$$\text{Flood}(x, y) = \begin{cases} 
1 & \text{if } M_{\text{Otsu}} + M_{\text{KI}} + \mathbb{I}(P_{\text{UNet}} \ge 0.5) \ge 2 \\ 
0 & \text{otherwise} 
\end{cases}$$
Pixels where all three methods agree receive confidence $c = 1.0$; two-method agreement yields $c = 0.67$.

### 3.3 Topographic False Positive Removal via DEM Slope
In rugged Himalayan valleys, radar shadows on northern/back slopes mimic water reflection. S.T.R.A.N.D computes localized terrain slope $\theta$ using Horn's algorithm on the 30-meter Copernicus DEM:
$$\theta = \arctan\left(\sqrt{\left(\frac{\partial z}{\partial x}\right)^2 + \left(\frac{\partial z}{\partial y}\right)^2}\right)$$
Because standing and slow-moving flood waters cannot pool on steep grades, any detection with $\theta > 15^\circ$ is rejected:
$$M_{\text{final}}(x, y) = \text{Flood}(x, y) \cdot \mathbb{I}(\theta(x, y) \le 15^\circ)$$
As demonstrated in Section 6, this single filter eliminates **98.1% of steep-terrain false alarms**.

---

## 4. Infrastructure Overlay & Network Vulnerability Analysis

### 4.1 Road and Bridge Damage Classification
Vector flood polygons are intersected against OpenStreetMap road segments $S_i$ and bridge points $B_j$:
- **Severed Road ($L_{\text{sev}}$):** Intersection ratio $\frac{\text{Length}(S_i \cap \text{Flood})}{\text{Length}(S_i)} \ge 0.50$
- **Partially Flooded Road ($L_{\text{par}}$):** $0.10 \le \text{Ratio} < 0.50$
- **Destroyed Bridge:** Bridge location within 100-meter flood buffer and buffer overlap $\ge 70\%$.

### 4.2 Directed Graph Reachability & Dijkstra Routing
Road segments form directed graph $G = (V, E, W)$:
- Severed edges are deleted from the post-disaster topology ($E_{\text{post}} = E \setminus E_{\text{sev}}$).
- Partially flooded edges remain traversable with an emergency clearance penalty ($W_{\text{post}}(e) = 5.0 \cdot W_0(e)$).
- Dijkstra shortest path trees are evaluated from all primary healthcare hubs $H = \{h_1, h_2\}$:
  $$d_{\text{post}}(s, H) = \min_{h \in H} \text{dist}_{G_{\text{post}}}(s, h)$$

### 4.3 Composite Urgency Formulation
Settlements are classified as **Connected**, **Degraded** ($d_{\text{post}} > 1.5 \cdot d_0$), or **Isolated** ($d_{\text{post}} = \infty$). For isolated settlements, S.T.R.A.N.D calculates a normalized urgency score:
$$\text{Urgency}(s) = 0.40 \cdot \hat{P}(s) + 0.35 \cdot (1 - \hat{D}_{\text{flood}}(s)) + 0.25 \cdot \mathbb{I}(\text{NoClinic})$$
where $\hat{P}(s)$ is min-max scaled population and $\hat{D}_{\text{flood}}$ is proximity to active floodwaters.

---

## 5. Tactical Innovation Modules

### 5.1 Autonomous Helicopter Landing Zone (HLZ) Finder
When roads are severed, aerial supply drops and medical evacuations are required. S.T.R.A.N.D executes an autonomous spatial search for safe HLZs:
1. Filters DEM for contiguous flat cells ($\theta \le 5^\circ$).
2. Aggregates cells into polygon regions requiring minimum rotor clearance: $\text{Area} \ge 400\text{ m}^2$ (standard Mil-Std-H-46855 / Mi-17 clearance).
3. Applies a 100-meter safety exclusion buffer from active flood polygons and ponding zones.
4. Ranks candidate sites by network geodesic distance to the highest-urgency isolated settlements.

### 5.2 Ponding Hazard Detection & D8 Flow Routing
Landslides and debris flows frequently form unstable temporary dams in narrow river gorges. S.T.R.A.N.D computes Planchon-Darboux depression filling on the DEM. If the depression depth $\Delta z > 3\text{m}$ and ponding volume $V > 50,000\text{ m}^3$, the zone is flagged as a high-risk debris dam. Downstream escape flow vectors are traced via D8 steepest descent:
$$k = \arg\max_{i \in [1, 8]} \frac{z_{\text{center}} - z_i}{d_i}$$

### 5.3 Bilingual Copilot with Zero-Hallucination Guardrails
To serve local Nepalese security forces and international agencies simultaneously, S.T.R.A.N.D embeds an LLM emergency copilot supporting English and Nepali (*नेपाली*). To eliminate hallucination risks in high-stakes triage:
- User queries are sanitized against SQL injection and jailbreak prompts.
- Queries are translated strictly into deterministic DuckDB spatial SQL queries.
- SQL execution runs on an isolated read-only connection.
- Output text must pass a numerical consistency cross-check against database ground truth.

---

## 6. Experimental Validation & Results

### 6.1 Benchmark against Copernicus EMS EMSR927
S.T.R.A.N.D was benchmarked against the Copernicus Emergency Management Service Rapid Mapping activation **EMSR927** (Bhote Koshi flood extent delineation product, 10m spatial resolution).

| Metric | S.T.R.A.N.D Result | Copernicus EMSR927 Target | Assessment |
|---|---|---|---|
| **Intersection over Union (IoU)** | **0.9514 (95.1%)** | $\ge 0.8000$ | Substantial concordance |
| **F1 Score (Dice Coefficient)** | **0.9751** | $\ge 0.8500$ | High balance |
| **Precision** | **0.9655** | $\ge 0.9000$ | Low false alarm rate |
| **Recall (Sensitivity)** | **0.9848** | $\ge 0.8800$ | Minimal missed water |
| **Specificity** | **0.9989** | $\ge 0.9500$ | Dry land preserved |
| **Overall Pixel Accuracy** | **0.9985 (99.8%)** | $\ge 0.9500$ | State-of-the-art |

```
                       EMSR927 Ground Truth
                    Flooded           Dry
Predicted  Flooded  TP:  2.891 km²   FP: 0.103 km²
           Dry      FN:  0.045 km²   TN: 96.961 km²
```

### 6.2 Ablation Study: DEM Slope Filter Impact
Conventional SAR change detection algorithms fail catastrophically in mountain terrain due to radar shadows on steep cliffs.

| Method | False Positive Extent | False Positive Reduction | IoU Score |
|---|---|---|---|
| Raw SAR Ensemble (No DEM) | 5.554 km² | Baseline (0.0%) | 0.3340 |
| S.T.R.A.N.D (with DEM Slope Filter $\le 15^\circ$) | **0.103 km²** | **98.1% Reduction** | **0.9514** |

```mermaid
pie title False Positive Elimination
    "Eliminated Mountain Shadows" : 98.1
    "Residual Edge Noise" : 1.9
```

### 6.3 Latency & Operational Timings
Tested on a standard 8-core CPU workstation with NVIDIA RTX 4080:
- SAR Calibration & Co-Registration: 14.2s
- Ensemble Change Detection & Morphology: 6.8s
- DEM Slope Mask & Polygon Vectorization: 3.5s
- Infrastructure Overlay & NetworkX Reachability: 5.4s
- HLZ & Hydro Analysis: 4.8s
- PDF SitRep & SMS Alert Generation: 3.7s
- **Total Pipeline Execution Time:** **38.4 seconds**  
*(Copernicus EMS manual analyst delivery typically requires 12–36 hours).*

---

## 7. Operational Deployment & Field Dissemination

```
[ S.T.R.A.N.D System ]
         │
 ┌───────┴───────────────────────┐
 ▼                               ▼
High-Bandwidth Operations     Last-Mile / Disconnected Field Teams
 • React + MapLibre GL 3D     • 140-char Satellite SMS (Garmin inReach)
 • Real-time WebSocket feed   • LoRa Mesh Field Radio Broadcast
 • Bilingual AI Copilot       • Offline GeoPDF & Vector MBTiles
 • UN OCHA Bilingual SitRep
```

1. **UN OCHA Bilingual SitRep:** Instant automated generation of standard Situation Reports in English and Nepali, formatted with headline loss numbers, triage queues, and legal copyright badges.
2. **LoRa & Satellite SMS Field Dispatch:** Automatic synthesis of compact, 140-character tactical emergency strings with zero internet requirements:
   ```
   [STRAND ALERT 0826] TATOPANI ISOLATED. Pop 1850. Araniko Hwy severed.
   Rec LZ: HLZ-2 (27.923N,85.930E,elev 1680m,slope 2.8deg). Next S1 pass 14h20m.
   ```

---

## 8. Limitations & Future Work
1. **Steep Slopes Inundation:** The $15^\circ$ slope mask correctly eliminates mountain shadows, but high-velocity water racing down steep ravines ($> 15^\circ$) is masked out until it reaches valley flats. Future iterations will incorporate kinematic wave momentum modeling.
2. **Revisit Latency:** Sentinel-1 constellation revisit interval is 6–12 days at Nepal's latitude. Future work will ingest NASA-ISRO SAR (NISAR) L-band and commercial ICEYE / Capella radar tasking for sub-6-hour revisit windows.

---

## 9. Conclusion
S.T.R.A.N.D demonstrates that space-borne radar combined with topographic physical modeling and graph analytics can overcome the classic "cloud cover blind spot" of humanitarian disaster response. By delivering validated 95.14% IoU flood mappings and prioritized isolation triage in under 40 seconds, S.T.R.A.N.D provides emergency commanders with the decisive intelligence needed to deploy resources, coordinate rescues, and save lives.

---

## References & Legal Attributions
1. Copernicus Emergency Management Service (EMS), Rapid Mapping Activation EMSR927 (August 2026).
2. European Space Agency (ESA), Sentinel-1 User Handbook, Standard Product Specification v3.11.
3. OpenStreetMap contributors (2026), Planet dump, licensed under Open Data Commons ODbL.
4. Horn, B. K. P. (1981). "Hill shading and the reflectance map." *Proceedings of the IEEE*, 69(1), 14-47.
5. Kittler, J., & Illingworth, J. (1986). "Minimum error thresholding." *Pattern Recognition*, 19(1), 41-47.

*Attribution Notices:*
- **Copernicus Sentinel Data:** Contains modified Copernicus Sentinel data (2026). Processed by S.T.R.A.N.D.
- **OpenStreetMap Data:** © OpenStreetMap contributors, licensed under ODbL.
- **Elevation Data:** Copernicus Digital Elevation Model (GLO-30), European Space Agency.
