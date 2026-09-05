# SIH 26143: 7-Person Team Division of Labor & Collaboration Plan
### Satellite Oil Spill Detection & AIS Correlation Platform

This document defines the roles, file boundaries, git protocol, and integration milestones for a 7-person engineering team:
- **3 Backend Engineers** (Data Infra, Ocean Drift Advection, AIS Scoring)
- **3 Frontend Engineers** (Geospatial Mapping, Suspect Dossier/Analytics, Ingestion Stepper/Workflow)
- **1 AI/ML Engineer** (UNet Deep Learning, Checkpoint Validation, Preprocessing)

---

## Team Architecture & Ownership Matrix

To prevent git merge conflicts and blocking dependencies, every team member has **exclusive file ownership** and explicit interfaces.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PROJECT REPOSITORY MAP                          │
├───────────────────┬──────────────────────────────────┬─────────────────┤
│ Team Role         │ Primary Working Directory        │ Restricted Out  │
├───────────────────┼──────────────────────────────────┼─────────────────┤
│ BE-1 (Infra/API)  │ apps/pipeline/, config/, tasks   │ ml_models/      │
│ BE-2 (Drift)      │ apps/drift/, metocean.py         │ apps/ais/       │
│ BE-3 (AIS)        │ apps/ais/, scoring.py, ingest.py │ apps/drift/     │
│ FE-1 (Map View)   │ src/components/map/ (or Leaflet) │ Form / Stepper  │
│ FE-2 (Analytics)  │ src/components/dashboard/, table │ Map layers      │
│ FE-3 (Workflow)   │ src/components/upload/, polling  │ Table details   │
│ ML-1 (AI Model)   │ ml_models/, scripts/validate*    │ config/, views  │
└───────────────────┴──────────────────────────────────┴─────────────────┘
```

---

## Detailed Role Specifications

### 1. Backend Engineer 1 (BE-1): Async Pipeline & Task Orchestrator
- **Focus:** Celery task coordination, Redis broker stability, pipeline lifecycle state management, and unified REST endpoints.
- **Owned Files:**
  - `apps/pipeline/models.py`
  - `apps/pipeline/orchestrator.py`
  - `apps/pipeline/tasks.py`
  - `apps/pipeline/views.py`
  - `config/settings.py` & `config/celery.py`
- **Key Responsibilities:**
  1. Maintain Celery task worker queues (`detection_queue`, `drift_queue`, `ais_queue`, `default`).
  2. Implement granular stage updates (`pending` -> `detecting` -> `drifting` -> `scoring` -> `completed` / `failed`) with execution latencies.
  3. Own the lightweight progress polling endpoint (`/api/v1/pipeline/<id>/status/`).
  4. Ensure Docker Redis and environment configuration remain smooth.
  5. Act as the **Database Migration Gatekeeper**: Only BE-1 merges Django migrations to prevent branching conflicts.

### 2. Backend Engineer 2 (BE-2): Met-Ocean Drift & Physical Oceanography Engine
- **Focus:** Ocean surface current and wind advection physics, Open-Meteo marine integration, caching, and backward trajectory calculation.
- **Owned Files:**
  - `apps/drift/engines/base.py`
  - `apps/drift/engines/lagrangian.py`
  - `apps/drift/metocean.py`
  - `apps/drift/views.py` & `apps/drift/models.py`
  - `tests/test_drift_engine.py` & `tests/test_metocean_cache.py`
- **Key Responsibilities:**
  1. Maintain and refine the Lagrangian particle advection engine ($\vec{V}_{drift} = \vec{V}_{current} + 0.03 \cdot \vec{V}_{wind}$).
  2. Expand Open-Meteo Marine API caching (1-hour Redis TTL to prevent rate limits).
  3. Ensure met-ocean data provenance (`open-meteo`, `manual_override`, `default_fallback`) is always populated in `DriftResult`.
  4. Calculate realistic spatial uncertainty growth ($\pm \text{km}$ uncertainty radius expanding backwards in time).
  5. Format trajectory waypoints as clean ISO-timestamped GeoJSON polylines.

### 3. Backend Engineer 3 (BE-3): AIS Spatial Ingestion & Vessel Scoring Engine
- **Focus:** AIS data ingestion, vectorized spatial filtering, behavioral anomaly detection, and composite suspect ranking.
- **Owned Files:**
  - `apps/ais/models.py`
  - `apps/ais/ingest.py`
  - `apps/ais/scoring.py`
  - `apps/ais/views.py`
  - `tests/test_ais_scoring.py`
- **Key Responsibilities:**
  1. Optimize MarineCadastre CSV batch ingestion with streaming/bulk loading.
  2. Maintain vectorized Haversine spatial proximity scoring near the estimated spill origin.
  3. Expand behavioral anomaly detection algorithms:
     - `ais_gap`: Transponder silence (>30 min gap).
     - `loitering`: Extended residence time at low speed in the slick origin zone.
     - `speed_change`: Sudden decelerations/accelerations indicating discharge operations.
  4. Calculate weighted composite ranking: $S = 0.40 \cdot S_{prox} + 0.35 \cdot S_{temp} + 0.25 \cdot S_{behav}$.
  5. Expose vessel track history endpoint (`/api/v1/ais/vessels/<mmsi>/track/`).

---

### 4. Frontend Engineer 1 (FE-1): Geospatial Cartography & Interactive Map
- **Focus:** Interactive map canvas (Leaflet / Mapbox GL / Deck.gl) displaying multi-layer satellite and maritime data.
- **Owned Components:**
  - `MapContainer`, `SpillLayer`, `TrajectoryLayer`, `VesselMarkerLayer`
- **Key Responsibilities:**
  1. Render GeoJSON spill polygon overlays with red semi-transparent fill and popup attributes (area in km², confidence).
  2. Render drift hindcast trajectories (blue dashed directional line) and forecast trajectories (green dashed line).
  3. Render estimated spill origin point with uncertainty circle marker.
  4. Plot AIS vessel positions and tracks, with distinct styling for Suspect #1 (red beacon) vs lower-ranked vessels.
  5. Add map layer controls (toggle Slick Mask, toggle Drift Tracks, toggle Vessel Route).

### 5. Frontend Engineer 2 (FE-2): Suspect Dossier, Analytics & Telemetry Dashboard
- **Focus:** Intelligence dashboard, ranked suspect tables, score breakdowns, and environmental telemetry cards.
- **Owned Components:**
  - `SuspectTable`, `VesselDetailDrawer`, `MetoceanTelemetryCard`, `MetricsOverview`
- **Key Responsibilities:**
  1. Build the ranked suspects table showing Rank (#1, #2, #3), Vessel Name, MMSI, Type, Composite Score, and Distance.
  2. Render behavioral anomaly tags (`ais_gap`, `loitering`, `speed_change`) with warning badges.
  3. Build the Met-Ocean Telemetry card displaying wind speed/direction, surface current speed/direction, and data source provenance badge (`open-meteo` vs `manual_override`).
  4. Build a vessel inspection drawer/modal that shows the vessel's dimensions, flag, and score breakdown (Proximity, Temporal, Behavioral).
  5. Add an "Export Intelligence Report" PDF/print button for hackathon judges.

### 6. Frontend Engineer 3 (FE-3): Workflow Stepper, Image Upload & Pipeline Poller
- **Focus:** Landing page, SAR/GeoTIFF upload zone, bounding box wizard, advanced parameters modal, and live progress state stepper.
- **Owned Components:**
  - `UploadZone`, `GeoRefForm`, `AnalysisStepper`, `PipelinePoller`
- **Key Responsibilities:**
  1. Build drag-and-drop file upload zone supporting SAR images and GeoTIFFs.
  2. Add optional georeference coordinate inputs (`min_lon`, `min_lat`, `max_lon`, `max_lat`) for non-GeoTIFF images.
  3. Add collapsible "Met-Ocean Controls" (allowing user overrides of wind/current if desired).
  4. Implement robust asynchronous polling against `/api/v1/pipeline/<id>/status/` every 1000ms.
  5. Display animated multi-step progress stepper:
     - Step 1: Deep Learning SAR Detection
     - Step 2: Met-Ocean Lagrangian Advection
     - Step 3: AIS Spatio-Temporal Correlation
     - Step 4: Ready (transitions to Results)
  6. Gracefully handle HTTP 400 Out-of-Domain rejections (e.g. optical photo alert).

---

### 7. AI / ML Engineer (ML-1): Deep Learning Model, Checkpoint Validator & Preprocessing
- **Focus:** Model architecture, training/fine-tuning weights, checkpoint validation, tile sliding inference, and preprocessing.
- **Owned Files:**
  - `ml_models/` (all weights and `model_info.json`)
  - `apps/detection/inference.py`
  - `apps/detection/preprocessing.py`
  - `apps/detection/postprocessing.py`
  - `scripts/validate_checkpoint.py`
- **Key Responsibilities:**
  1. Ensure any new model checkpoint strictly complies with the I/O tensor contract:
     - **Input:** `(1, 3, 256, 256)` float32 normalized
     - **Output:** `(1, 1, 256, 256)` float32 logits/probabilities
  2. Maintain the `model_info.json` sidecar for every model version.
  3. Run the automated 6-step validation gate before handing off any weights:
     ```bash
     python manage.py validate_model --checkpoint ml_models/candidate_model/model.pt
     ```
  4. Compare new candidate models against baseline using the side-by-side SAR calibration benchmark (`calibration_data/known_sar_spill.jpg`).
  5. Deliver new models by updating `.env` (`MODEL_CHECKPOINT_PATH=...`) without editing orchestrator or backend code.

---

## Git Workflow & Branching Conventions

```
main (always stable, all tests passing)
 ├── feature/be-1-infra
 ├── feature/be-2-drift
 ├── feature/be-3-ais
 ├── feature/fe-1-map
 ├── feature/fe-2-dashboard
 ├── feature/fe-3-upload-flow
 └── feature/ml-1-model-v2
```

### Git Golden Rules:
1. **Branch Naming:** Prefix all branches with your role tag (e.g., `feature/fe-1-map-layers`, `fix/be-2-meteo-cache`).
2. **Never Touch Other Apps:** BE-2 does not edit `apps/ais/`; FE-1 does not edit the upload form.
3. **Database Migrations:** Only **BE-1** generates or modifies Django migrations. If your model changes, coordinate with BE-1.
4. **CI Verification Before PR:** Every branch must pass `./setup.sh` and `pytest` with 0 failures before opening a pull request.
5. **Contract-First API:** Backend devs must keep the Swagger schema at `/api/schema/` updated. Frontend devs build against TypeScript interfaces in `FRONTEND_INTEGRATION.md`.

---

## 3-Day Hackathon Sprint Milestones

### Day 1: Foundation & Contract Verification
- **All:** Run `./setup.sh` locally. Confirm Redis, Django, and tests are passing.
- **Frontend (FE-1, 2, 3):** Scaffold frontend project (Next.js / Vite React). Set up API client with `types/api.ts`.
- **Backend (BE-1, 2, 3):** Verify Celery queue routing, Open-Meteo marine caching, and AIS CSV test data ingestion.
- **ML (ML-1):** Validate baseline model on CUDA/CPU. Prepare benchmark suite for new candidate checkpoint.

### Day 2: Parallel Feature Acceleration
- **FE-1:** Implement Leaflet map with GeoJSON slick polygons and dashed drift lines.
- **FE-2:** Implement Suspect table, anomaly badges, and met-ocean telemetry card.
- **FE-3:** Implement Upload drag-and-drop, coordinate inputs, and polling progress stepper.
- **BE-1:** Implement stage breakdown latencies and optimize polling endpoint.
- **BE-2:** Add uncertainty radius calculation and refine Lagrangian advection.
- **BE-3:** Benchmark vectorized AIS Haversine query on 50,000+ MarineCadastre records.
- **ML-1:** Plug in new checkpoint, run `python manage.py validate_model`, verify side-by-side calibration matrix, and update `.env`.

### Day 3: End-to-End Integration, Pitch Polish & Demo Hardening
- **Joint FE + BE:** Connect live frontend to `http://localhost:8000/api/v1/pipeline/run/`.
- **FE:** Polish dark-mode UI, loading skeletons, tooltips, and map reset buttons.
- **BE + ML:** Run stress tests on large SAR scenes (1024x1024) and verify error messages for OOD / non-georeferenced images.
- **Team:** Rehearse presentation demo:
  1. Upload real SAR image with slick.
  2. Watch live 4-stage pipeline execution.
  3. View detected slick on map.
  4. Follow hindcast drift line back 24 hours to estimated origin.
  5. Identify Suspect #1 (e.g., tanker with AIS transponder gap anomaly).
