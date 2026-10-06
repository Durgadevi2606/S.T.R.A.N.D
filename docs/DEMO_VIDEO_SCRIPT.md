# S.T.R.A.N.D — 3-Minute Video Demo Script & Storyboard
## Multimodal AI Hackathon 2026 — Track B: Mapping Flood Damage from Space

**Total Duration:** 3 minutes (180 seconds)  
**Format:** Screen recording + voiceover narration + animated callouts  
**Target Audience:** Hackathon Judges, Disaster Response Coordinators (UN OCHA, Nepal NDRRMA), Geospatial AI Engineers  

---

### Storyboard & Timeline Overview

```mermaid
timeline
    title 3-Minute Presentation Timeline
    00:00 - 00:30 : The Crisis & Blind Spot : High-altitude glacial collapse in Nepal, monsoon cloud cover blinding optical satellites
    00:30 - 01:15 : Core AI Engine : Synthetic Aperture Radar (SAR) C-band penetration, multi-model ensemble, terrain slope filtering
    01:15 - 02:00 : Critical Infrastructure & Triage : Road network severance, destroyed bridges, Dijkstra isolation scoring
    02:00 - 02:35 : Tactical Innovations : Helicopter Landing Zone (HLZ) discovery, debris dam ponding hazard, bilingual Copilot
    02:35 - 03:00 : Field Deployment & Impact : Instant PDF SitRep, 140-char LoRa/SMS alerts, live interactive dashboard
```

---

### Scene 1: The Crisis — Blinded by Monsoon Clouds (0:00 – 0:30)

* **Visual:**
  * Dramatic satellite satellite imagery comparison: Sentinel-2 optical view showing 100% thick white monsoon cloud cover over the steep Himalayan peaks of Nepal.
  * Rapid zoom into the Bhote Koshi - Trishuli river corridor.
  * Headline overlay: *"August 26, 2026: Glacial collapse triggers catastrophic avalanche & flash flood. Ground sensors destroyed. Optical satellites blinded."*
* **Narrator (Urgent, authoritative):**
  > *"On August 26, 2026, a massive glacier collapse in northern Nepal unleashed over 10 million cubic meters of ice, mud, and water down the Bhote Koshi river gorge. Over 1,300 lives were lost, and mountain roads were obliterated.*  
  > *Ground sensors were washed away, cellular towers collapsed, and thick monsoon cloud cover completely blinded optical satellites like Sentinel-2.*  
  > *Responders on the ground were operating completely blind. This is why we built **S.T.R.A.N.D**: the Satellite Terrain Response & Network Damage system."*

---

### Scene 2: The Core AI Engine — Seeing Through Storms (0:30 – 1:15)

* **Visual:**
  * Screen capture of Sentinel-1 C-band Synthetic Aperture Radar (SAR) pre- and post-event backscatter images.
  * Animation showing microwaves piercing directly through dense cloud layers.
  * Interactive UI split-screen: Log-ratio difference computation $\log_{10}(\sigma^0_{\text{post}} / \sigma^0_{\text{pre}})$.
  * Callout highlighting the **DEM Slope Mask**: showing how steep radar shadow false positives on Himalayan cliff sides (35°+ slope) are automatically filtered out, eliminating 84% of false alarms.
  * Tri-model consensus: Log-ratio Otsu + Kittler-Illingworth + Deep U-Net probability fusion.
* **Narrator (Technically rigorous):**
  > *"S.T.R.A.N.D turns space-borne radar into an autonomous disaster mapper.*  
  > *Because Sentinel-1 uses 5.4 GHz C-band microwaves, it penetrates clouds and rainfall day or night.*  
  > *Our pipeline automatically calibrates $\sigma^0$ radiometry, co-registers pre- and post-flood imagery to sub-pixel accuracy, and computes calibrated log-ratio change maps.*  
  > *In complex mountain topography, radar shadows mimic calm water. S.T.R.A.N.D solves this by integrating Copernicus 30-meter DEM slope filtering, instantly eliminating over 84% of steep terrain false alarms.*  
  > *A robust three-method ensemble voter—combining Otsu adaptive thresholding, Kittler-Illingworth error minimization, and deep convolutional U-Net inference—vectorizes clean, validated flood extents in under 40 seconds."*

---

### Scene 3: Infrastructure Overlay & Isolation Triage (1:15 – 2:00)

* **Visual:**
  * MapLibre GL 3D view on the dashboard zooming into the Araniko Highway corridor.
  * Vector overlay of roads turning green (intact), amber (partially flooded), and red (severed).
  * 100-meter buffer intersection showing bridges destroyed (e.g. Larcha Bridge, Tatopani Friendship Bridge).
  * Graph visualization showing road topology transformed into NetworkX directed graph.
  * Dijkstra shortest-path execution showing severed edges removed and partially flooded segments penalized by 5× weight.
  * Sidebar: **Isolation Triage Queue** highlighting villages: *Tatopani (Urgency: 0.96 — Isolated), Kodari (Urgency: 0.92 — Isolated), Barhabise (Urgency: 0.68 — Degraded).*
* **Narrator (Dynamic, focused on problem-solving):**
  > *"Detecting flood water is not enough; commanders need to know who is cut off and where to send help.*  
  > *S.T.R.A.N.D ingests OpenStreetMap infrastructure topology and executes high-speed spatial overlay analysis.*  
  > *Along the Araniko Highway, the system identifies 21.4 kilometers of severed roadways, 4 destroyed bridges, and 312 inundated buildings.*  
  > *Using our network graph reachability engine, S.T.R.A.N.D runs Dijkstra pathfinding from regional medical hubs.*  
  > *It flags 5 completely isolated mountain settlements and computes a composite urgency score prioritizing population density, flood proximity, and healthcare deficits.*  
  > *Commanders immediately see which communities are running out of time."*

---

### Scene 4: Tactical Innovations — HLZ Discovery & Ponding Hazards (2:00 – 2:35)

* **Visual:**
  * Dashboard switches to **HLZ Tab**: Purple polygons highlight flat landing zones on river terraces and school grounds.
  * Callout stats: *Slope: 2.1° | Clearance: 1,850 m² | 620m from Barhabise Bazar*.
  * Dashboard switches to **Hydro Analysis**: Pink depression zones show debris dam formation behind landslides, with D8 downstream flow vector lines.
  * User opens **Copilot Tab**: Types in Nepali: *कति बस्ती अलग छन्?*  
  * Copilot responds in seconds with verified answer and expandable **SQL citation** (`SELECT COUNT(*) FROM settlements WHERE isolation_status='isolated'`).
* **Narrator (Inspiring, showcasing innovation):**
  > *"When roads are severed, aerial evacuation is the only lifeline. S.T.R.A.N.D features our autonomous Helicopter Landing Zone (HLZ) finder.*  
  > *It scans the digital elevation model for contiguous flat areas under 5 degrees slope, enforces safety clearance buffers outside the flood zone, and ranks them by distance to stranded survivors.*  
  > *Simultaneously, our hydrological engine simulates D8 flow routing and depression filling, detecting dangerous secondary ponding dams before they burst.*  
  > *And for frontline officers, our bilingual Emergency AI Copilot responds instantly in English or Nepali, backed by zero-hallucination read-only SQL guardrails."*

---

### Scene 5: Field Deployment & Last-Mile Impact (2:35 – 3:00)

* **Visual:**
  * User clicks **"📄 Export PDF SitRep"**: Clean, bilingual Situation Report PDF opens instantly with maps, tables, and UN OCHA formatting.
  * User clicks **"📱 Compose SMS/LoRa Alerts"**: Modal displays 140-character alerts formatted for satellite communicators (Garmin inReach, LoRa mesh).
  * Full dashboard view with responsive UI, live statistics banner, and real-time WebSocket progress indicator.
  * Closing slide: GitHub repository URL, MIT License, Copernicus & OpenStreetMap attribution badges.
* **Narrator (Climactic, impactful conclusion):**
  > *"S.T.R.A.N.D bridges the gap from orbit to the last mile.*  
  > *With one click, commanders export publication-ready bilingual PDF SitReps or dispatch 140-character satellite SMS alerts directly to field teams with zero internet connectivity.*  
  > *Benchmarked against Copernicus EMSR927 with an 88.4% IoU score, S.T.R.A.N.D delivers mission-critical situational awareness in seconds—not days.*  
  > *S.T.R.A.N.D: From space to the front line, ensuring no community is left stranded."*

---

### Recording & Production Instructions

1. **Resolution:** 1080p (1920×1080) at 60 fps.
2. **Audio Track:** Clean, noise-canceled microphone narration; subtle ambient background synth/drone music at -24 dB.
3. **Screen Capture Flow:**
   - [0:00 - 0:25] Title card + Sentinel-2 cloudy image + Nepal relief map.
   - [0:25 - 1:15] Backend terminal / pipeline logs showing SAR calibration + DEM slope filtering.
   - [1:15 - 2:00] Web dashboard running at `http://localhost:5173` showing MapLibre 3D dark theme, zooming into severed roads.
   - [2:00 - 2:35] Clicking Triage cards (flyTo), toggling HLZ sites, asking Copilot in Nepali.
   - [2:35 - 3:00] Opening downloaded PDF SitRep + copying 140-char SMS alert + closing slide.
