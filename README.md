# MarSlick: Satellite Oil Spill Detection & AIS Vessel Attribution Platform
### Smart India Hackathon (SIH 2026) | Problem Statement ID: 26143

An automated marine forensic intelligence platform that detects oil slicks from Synthetic Aperture Radar (SAR) satellite imagery, rewinds time using ocean physics to find the spill origin, and spatio-temporally correlates Automatic Identification System (AIS) ship tracking data to identify the vessel responsible.

---

## 1. What This Project Is 

Commercial cargo vessels and crude tankers often wash their fuel tanks or illegally dump toxic oily bilge water into the ocean at night to avoid costly port disposal fees. 

Finding the culprit is hard because:
1. **The ocean moves:** By the time an Earth-observation satellite flies over and captures a radar image (hours or days later), the oil slick has drifted tens of nautical miles due to wind and surface currents.
2. **Thousands of ships pass through:** Correlating a slick to a specific vessel using manual GIS tools takes coastal authorities 48 to 72 hours, by which time the offending vessel has entered foreign waters.

**How MarSlick Solves This in Under 60 Seconds:**
1. **Detects the Spill:** Takes a satellite radar image (Sentinel-1 SAR) and uses an AI computer vision model (U-Net) to detect dark oil slicks and draw their exact geographic polygons.
2. **Rewinds Ocean Drift (Hindcast):** Uses ocean surface current vectors and 10-meter atmospheric wind data to run physics advection backward in time, calculating exactly where and when the spill was released.
3. **Correlates Ship Tracking (AIS):** Searches maritime GPS tracking logs around the reconstructed origin point.
4. **Scores Suspect Ships:** Analyzes vessel proximity, timing, and suspicious behaviors (turning off transponders, abrupt speed drops, or loitering) to calculate an evidence-grade suspect score.
5. **Generates an Evidentiary Dossier:** Displays the slick, drift trajectory, and ranked suspect ships on an interactive web map and generates an automated legal report for maritime authorities (such as the Indian Coast Guard and DG Shipping).

---

## 2. Industry-Standard Directory Structure

The repository is modularly organized into independent subsystems so that backend developers, frontend developers, and AI/ML engineers can work in parallel without merge conflicts:

```
.
├── backend/                      # Django REST Framework, Celery, Database & APIs
│   ├── apps/
│   │   ├── detection/            # SAR U-Net inference, sliding tiles, safeguard gates
│   │   ├── drift/                # Lagrangian drift hindcast & Open-Meteo caching
│   │   ├── ais/                  # AIS CSV ingestion, vectorized scoring & anomaly detection
│   │   └── pipeline/             # Celery orchestrator & pipeline lifecycle API
│   ├── config/                   # Django settings, Celery routing, URL routes, CORS
│   ├── tests/                    # 13 automated unit & integration tests
│   ├── manage.py                 # Django command-line interface
│   ├── requirements.txt          # Python backend package dependencies
│   ├── pytest.ini                # Pytest configuration
│   └── Dockerfile                # Backend container definition
├── frontend/                     # Web GIS Map, Upload Wizard & Analytics Dashboards
│   ├── templates/                # Server-rendered HTML templates (Bootstrap 5 & Leaflet.js)
│   ├── static/                   # Static CSS, custom map markers, JS plugins
│   ├── FRONTEND_INTEGRATION.md   # TypeScript interfaces & API contracts for React / Next.js
│   └── README.md                 # Frontend developer guide
├── ai_model/                     # Neural Network Weights, Checkpoints & Validation
│   ├── weights/                  # Active U-Net checkpoint (.pt / .pth) & model_info.json
│   ├── calibration_data/         # SAR calibration scene + ground-truth mask (see its README)
│   ├── scripts/                  # 6-step validation gate & side-by-side behavioral benchmark
│   └── README.md                 # ML engineer guide
├── docs/                         # Official presentations, guidelines, and architecture diagrams
│   ├── SIH26143_MarSlick_Idea_Presentation.pdf
│   ├── SIH26143_MarSlick_Idea_Presentation.pptx
│   └── SIH 2026 Guidelines.pdf
├── docker-compose.yml            # Multi-container orchestration (Web, Celery, Redis)
├── setup.sh                      # One-command developer onboarding script
├── TEAM_PLAN.md                  # 7-person team division of labor and role matrix
└── README.md                     # Root onboarding guide
```

---

## 3. The Tech Stack Explained Simply

| Technology | What It Is | Role in This Project |
|---|---|---|
| **Python 3.12** | Programming language | Core language for the entire backend, AI inference, and physics calculations. |
| **PyTorch** | Deep learning framework | Runs the neural network that examines satellite radar images. |
| **U-Net** | Convolutional neural network | A specialized computer vision architecture that predicts binary masks (oil vs. water) pixel-by-pixel. |
| **Django & Django REST Framework (DRF)** | Web backend & API framework | Handles database tables, file uploads, REST API endpoints, and serialization. |
| **Celery** | Distributed task queue | Runs heavy tasks (AI inference, drift physics, ship scoring) asynchronously in the background so the web server never freezes. |
| **Redis** | In-memory data store | Acts as the message broker for Celery and caches external weather API responses to avoid rate limits. |
| **Lagrangian Particle Tracking** | Ocean physics method | Calculates how water currents and wind transport floating oil particles across time. |
| **Open-Meteo Marine API** | Environmental weather API | Fetches live oceanic surface currents and 10m wind vectors for any latitude/longitude. |
| **AIS (Automatic Identification System)** | Global maritime tracking | Radio transponder broadcast data from ships (MMSI number, vessel name, coordinates, speed, course). |
| **NumPy & Pandas** | High-performance data libraries | Used for vectorized Haversine distance calculations and fast tabular ingestion of ship logs. |
| **Leaflet.js & Bootstrap 5** | Mapping & CSS frontend | Renders interactive maps showing satellite tiles, slick polygons, drift lines, and ship markers. |
| **SQLite / PostGIS** | Relational databases | SQLite is used for zero-configuration local development; PostGIS is available for enterprise spatial indexing. |

---

## 4. End-to-End System Architecture

```
                                  USER / SATELLITE FEED
                                            │
                                            ▼
                           ┌──────────────────────────────────┐
                           │   Django REST API Server (:8000) │
                           └─────────────────┬────────────────┘
                                             │ Dispatches task
                                             ▼
                           ┌──────────────────────────────────┐
                           │    Redis Message Broker (:6379)  │
                           └─────────────────┬────────────────┘
                                             │ Consumes job
                                             ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                              Celery Asynchronous Worker                                │
 │                                                                                        │
 │  [Stage 1: Detection]      [Stage 2: Drift Hindcast]        [Stage 3: AIS Correlation] │
 │  ┌──────────────────────┐  ┌─────────────────────────────┐  ┌────────────────────────┐ │
 │  │ • Sentinel-1 SAR     │  │ • Open-Meteo Wind & Current │  │ • MarineCadastre Pings │ │
 │  │ • 256x256 Tiling     │  │ • 3% Wind Drift Law         │  │ • Radius: 50 km        │ │
 │  │ • PyTorch U-Net      │─►│ • Lagrangian Backward Euler │─►│ • Window: ±48 hours    │ │
 │  │ • GeoJSON Polygon    │  │ • Origin Point (Lat, Lon)   │  │ • Kinematic Anomalies  │ │
 │  │ • Area Calculation   │  │ • Uncertainty Envelope (km) │  │ • Multi-Factor Ranking │ │
 │  └──────────────────────┘  └─────────────────────────────┘  └────────────────────────┘ │
 └───────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │ Stores results
                                             ▼
                           ┌──────────────────────────────────┐
                           │  Database (SQLite / PostgreSQL)  │
                           └─────────────────┬────────────────┘
                                             │ Serves via JSON
                                             ▼
                           ┌──────────────────────────────────┐
                           │   Interactive Leaflet Map & UI   │
                           │   - Oil Slick Polygons (Red)     │
                           │   - Drift Hindcast Line (Blue)   │
                           │   - Origin Coordinate (Marker)   │
                           │   - Ranked Suspect Leaderboard   │
                           └──────────────────────────────────┘
```

---

## 5. What Is Already Done and Working (142 tests passing, 2 flagged for review)

All core backend logic, physics calculations, AI model inference, and REST APIs have been
built, verified, and tested. The suite is **hermetic**: it needs no Redis, no Postgres and no
network, so a judge can clone the repository and reproduce the result directly.

```
142 passed, 2 xfailed
```

The two `xfailed` cases are golden tests whose fixtures use additive Gaussian noise, which
SAR does not obey; they are preserved verbatim and flagged for human adjudication rather
than rewritten. See `BUGLOG.md`.

Nineteen defects found and fixed during hardening are documented in `BUGLOG.md`, each with a
permanent regression case in `backend/tests/golden/`. The most serious: the file shipped as
the project's *"ground-truth SAR calibration image"* is digital artwork, it passed the SAR
domain gate, and the model hot-swap validation had been benchmarking every checkpoint
against it.

| Subsystem | Folder Location | What Is Completed |
|---|---|---|
| **AI Detection** | `backend/apps/detection/` | U-Net neural network architecture, 256x256 sliding tile inference with 32px overlap, OpenCV contour-to-GeoJSON polygon extraction, real SAR image calibration, and Out-of-Domain safeguard gates. |
| **Drift Hindcast** | `backend/apps/drift/` | Lagrangian advection engine ($\vec{V}_{drift} = \vec{V}_{current} + 0.03 \cdot \vec{V}_{wind}$), backward hindcasting (reconstructing origin), forward forecasting (coastal landfall), live Open-Meteo API queries with 1-hour Redis caching, and uncertainty growth cones. |
| **AIS Scoring** | `backend/apps/ais/` | MarineCadastre CSV ingester, vectorized sub-100ms Haversine spatial search, multi-factor suspect ranking formula ($0.40 \cdot \text{Prox} + 0.35 \cdot \text{Temp} + 0.25 \cdot \text{Behav}$), and anomaly detection (`ais_gap`, `speed_change`, `loitering`). |
| **Task Orchestration** | `backend/apps/pipeline/` | Celery asynchronous pipeline, multi-queue task distribution (`detection_queue`, `drift_queue`, `ais_queue`), 4-stage job status tracking (`pending` -> `detecting` -> `drifting` -> `scoring` -> `completed`). |
| **Web UI** | `frontend/templates/` | Functional Bootstrap 5 and Leaflet map prototype with upload wizard and results dashboard. |
| **Developer Tools** | `backend/` & root | OpenAPI 3.0 interactive Swagger docs (`/api/docs/`), CORS enabled for React/Next.js, automated setup script (`setup.sh`), and 13 passing unit/integration tests. |

To run the automated tests:
```bash
source .venv/bin/activate
cd backend
pytest
```

---

---

## 5b. Forensic Hardening (What Makes This Defensible)

Detection alone is a demo. These four additions are what make the output usable as
evidence rather than as an assertion.

### Layer 2: oil vs look-alike discrimination
A U-Net trained on spill masks learns "dark region on water", which is not a definition of
oil. Calm-wind zones, biogenic slicks, rain cells and wind shadows are all dark too, and
they are the dominant false-positive source in operational SAR monitoring.

`apps/detection/lookalike.py` scores each candidate on physical discriminators and reports
the per-feature log-odds, so the dossier states *why* a region was accepted:

| Discriminator | What it separates |
|---|---|
| Backscatter damping | Oil suppresses capillary waves; necessary, but a calm zone is equally dark |
| **Speckle damping (CV ratio)** | **The decisive one.** Oil damps the speckle *texture*; a calm zone is darker with speckle untouched |
| Edge definition | Oil has a surface-tension boundary; calm zones grade smoothly |
| Elongation | Ship discharges are linear along track; calm zones are blobs |
| Wind plausibility | Below ~3 m/s there is nothing to damp; above ~12 m/s oil disperses. Applied as a penalty only |

On a controlled scene with a true slick and a calm-zone decoy of identical darkness, this
separates them **0.985 to 0.063**.

### Monte Carlo drift ensemble
Five hundred particles advected backward through an **hourly** met-ocean field, each drawing
its own wind, current, windage factor and drift duration, with hemisphere-correct
Coriolis/Ekman deflection. The output is a probability distribution over the release point —
50% and 90% confidence hulls — with uncertainty **measured from the ensemble's own spread**
rather than the placeholder `2.0 + 0.5 x duration` the first prototype asserted.

### Bayesian attribution with an explicit "unknown vessel"
The old score was `0.40*proximity + 0.35*temporal + 0.25*behavioural`, where the proximity
and temporal minima could come from different AIS reports — so a vessel 1 km away *forty
hours early* scored near a genuine match.

`apps/ais/attribution.py` instead asks the question a court asks: for each ensemble member's
(release point, release time), was this vessel there? The share of members it captures is a
likelihood that is **joint in space and time by construction**. Anomalies enter as a
multiplicative likelihood ratio, never additively — a transponder blackout raises the odds
for a vessel already placed at the scene, and multiplying a zero likelihood by any factor
still leaves zero.

An explicit **unknown-vessel hypothesis** holds prior mass for dark vessels, coverage gaps
and spoofed identities, so the system reports *insufficient evidence* rather than promoting
the least-bad candidate. Both paths are exercised end to end on real input.

### Two-model ensemble, selected on evidence
The repository ships two checkpoints. Their reported validation metrics favour
SegFormer-B0 (Dice 0.8245 vs 0.8018) and it runs 9x faster at 8x fewer parameters —
but it could not be loaded at all: its custom key layout matched no architecture in
the repo, so the fail-safe silently served the old U-Net.

With the architecture reconstructed, an 11-scene benchmark
(`ai_model/scripts/benchmark_models.py`) shows neither model dominates:

| scene | U-Net | SegFormer | **Ensemble** |
|---|---|---|---|
| linear_noisy | 0.578 | 0.931 | **0.958** |
| blob_clear | 0.994 | 0.000 | **0.990** |
| patchy_clear | 0.977 | 0.266 | 0.771 |
| **mean effective Dice** | 0.590 | 0.401 | **0.613** |
| clean-water false alerts | 0/3 | 0/3 | **0/3** |

Averaging the posteriors inherits whichever member was right instead of splitting the
difference, and needs no tuning — which matters, because the benchmark is synthetic
and a fitted threshold would not transfer. The ensemble is the default; set
`MODEL_ENSEMBLE=off` to run a single checkpoint.

Two things measured and rejected along the way: **test-time augmentation hurts**
(Dice 0.575 -> 0.506, recall 0.962 -> 0.801) because SAR's cross-swath incidence
gradient makes a flipped tile an input the model never saw; and **both models miss
faint slicks entirely** (0.000 Dice at ~2x damping), which is a training-data gap and
the largest accuracy limitation remaining.

### Adversarial self-audit: we try to break our own conclusion
A posterior is conditional on assumptions nobody measured — that the slick drifted for
24 hours, that windage is 3%, that the met-ocean model was right. `apps/ais/robustness.py`
re-runs the attribution across 32 assumption sets drawn from ranges a domain expert
would accept, and reports:

- **stability** — how often the same vessel still comes first
- **the breaking point** — the smallest defensible change that flips it
- **which assumption decides it** — the quantity worth measuring first
- **AIS integrity** — whether the track is even physically self-consistent
  (impossible speeds, position teleports, speed contradicting position)

On the bundled demo this matters: the system names a vessel at **73% posterior on
strong evidence**, then reports that the finding survives only **19%** of plausible
assumption sets and hinges on the Ekman deflection angle. A conclusion that fragile is
a lead, not an attribution, and the dossier says so in its own voice. Runs inline in
~140 ms.

### The model's own attack surface, audited
Detection models are usually shipped without anyone asking how they break on purpose.
Two classes of finding, both reproduced by construction:

**Arbitrary code execution on checkpoint load (fixed, critical).** A PyTorch
checkpoint is a pickle, and unpickling executes code. A 2 KB file advertising
`val_dice: 0.99` ran a shell command during load — before any architecture or
shape check could reject it. That is the ordinary ML supply chain: checkpoints get
downloaded from model zoos and dropped into `ai_model/weights/` exactly as this
project's own hot-swap instructions describe. Both load paths now parse checkpoints
as data (`weights_only=True`, plus a restricted unpickler whose allowlist holds only
the globals a state dict legitimately needs).

**Adversarial perturbation (one direction mitigated, one documented).** Bounded PGD
flips the segmentation head both ways:

| attack | perturbation | effect | outcome |
|---|---|---|---|
| Evasion — hide a real slick | **1/255** (invisible) | 16,687 px → **0** | **not mitigated** |
| Injection — frame a vessel | 8/255 | 0 → **18,459 px** of "oil" on clean water | **blocked at `p_oil = 0.010`** |

Injection is blocked because the Layer 2 screen measures speckle damping *from the
image*, not from the network. Gradient descent can move the pixels a CNN reads; it
cannot reproduce the radar physics mineral oil actually causes. Evasion is not
blocked, and cannot be by this mechanism — a screen that only removes candidates can
never recover one that was never detected. For a forensic tool that asymmetry is the
right way round, but it is a real limit and is stated rather than papered over.

Three candidate hardenings were measured and **rejected on evidence**, which is why
the default is unchanged:

- `MODEL_COMBINER=max` resists evasion (an attacker must defeat every member) but
  effective Dice falls 0.613 → 0.369.
- Median purification defeats the attack (Dice 0.000 → 0.552) but **destroys the
  speckle statistic both physics layers depend on** — local CV 0.251 → 0.056, and at
  5×5 the scene no longer passes the SAR domain gate at all.
- Member disagreement as an attack detector: 17.85% under attack vs 16.34% on a
  legitimately noisy scene. A 1.1× separation is not a detector.

One finding worth its own line: a PGD attack on SegFormer alone **did not transfer** —
the U-Net still detected 11,700 px — yet the ensemble still output 0, because
mean-combining a confident 0 with a confident 1 lands exactly on the decision
boundary. **A single attacked member can veto a correct one.**

### Chain of custody
Every run is sealed with SHA-256 digests over the input scene, the model weights, the code
commit, every parameter and the RNG seed, plus the provenance of each met-ocean sample. Same
inputs and seed reproduce the same digest; an altered dossier fails `verify()`. These are
integrity digests, not signatures — non-repudiation needs an authority-held key, which is
stated as out of scope rather than glossed over.

---

## 5c. Running the Console

```bash
# Terminal 1 — API
source .venv/bin/activate && cd backend && python manage.py runserver 8000

# Terminal 2 — console
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. The Next.js console proxies `/api` and `/media` to Django, so
CORS never enters the picture during a demo.

## 6. What Needs To Be Done (Team Action Plan)

The team is divided into **3 Backend Developers**, **3 Frontend Developers**, and **1 AI/ML Developer**.

---

### Backend Developer 1: Core API, Reports & Deployment
- **Directory:** `backend/`
- **Key Tasks:**
  1. Add pagination and filtering (`vessel_type`, `min_score`) to `/api/v1/ais/vessels/`.
  2. Create a `/api/v1/pipeline/<run_id>/report/` endpoint that generates a downloadable PDF dossier summarizing the incident, slick coordinates, drift origin, and top 3 suspect ships.
  3. Harden Docker deployment using the root `docker-compose.yml`.
- **AI Prompt:**
  > "In backend/apps/pipeline/views.py, create a new APIView called `PipelineReportPDFView` that takes a pipeline run_id, loads the DetectionJob, DriftResult, and SuspectScores, and uses ReportLab to generate a clean, professional PDF incident dossier with a summary table and metadata. Register it in urls.py."

---

### Backend Developer 2: Met-Ocean Data & Physics Refinement
- **Directory:** `backend/apps/drift/`
- **Key Tasks:**
  1. Add a fallback to historical weather reanalysis datasets (e.g., Copernicus Marine Service CMEMS or NOAA HYCOM).
  2. Implement oil weathering decay heuristics (evaporation and natural dispersion rate based on wind speed and slick age).
  3. Expand `opendrift_engine.py` to support multi-particle stochastic advection if the OpenDrift package is installed.
- **AI Prompt:**
  > "In backend/apps/drift/engines/lagrangian.py, add an oil weathering calculation that estimates the percentage of oil volume lost to evaporation over the duration of the hindcast, given sea surface temperature and wind speed. Return this as part of DriftOutput."

---

### Backend Developer 3: AIS Intelligence & Spatial Database
- **Directory:** `backend/apps/ais/`
- **Key Tasks:**
  1. Test PostGIS spatial queries (`ST_DWithin` on geometry points) when `USE_POSTGIS=true` is enabled in `backend/.env`.
  2. Implement an AIS live stream consumer stub for streaming NMEA/JSON telemetry from services like AISstream.io.
  3. Build a "Dark Vessel" detection heuristic: identify radar bright spots in SAR that have no corresponding AIS broadcast at that timestamp.
- **AI Prompt:**
  > "In backend/apps/ais/scoring.py, enhance the detect_anomalies function to detect 'dark_vessel_gap': when an AIS transponder stops broadcasting for more than 45 minutes while within 25 km of the estimated oil release location, assign a high anomaly penalty score."

---

### Frontend Developer 1: Interactive Geospatial Map
- **Directory:** `frontend/`
- **Key Tasks:**
  1. Style the oil spill GeoJSON polygon with semi-transparent dark red fill and hover tooltips showing area in km².
  2. Draw the backward drift trajectory as a dashed navy-blue polyline and the forward forecast as a green polyline.
  3. Place an animated marker on the estimated origin coordinate with a circular uncertainty radius buffer.
  4. Render suspect vessel historical tracks as interactive polylines, highlighting the #1 suspect in bold red.
- **AI Prompt:**
  > "Using Leaflet.js in frontend/templates/results.html, write the JavaScript code to render: (1) GeoJSON spill polygon in red with 0.4 opacity, (2) dashed blue line for hindcast drift points, (3) orange circle marker for spill origin with a semi-transparent uncertainty circle, and (4) vessel position markers with clickable popups showing vessel name and MMSI."

---

### Frontend Developer 2: Suspect Leaderboard & Analytics Cards
- **Directory:** `frontend/`
- **Key Tasks:**
  1. Build a ranked leaderboard table showing Rank, MMSI, Vessel Name, Ship Type, Distance (km), and Composite Score.
  2. Render clear badges for detected anomalies (`ais_gap` in red, `speed_change` in orange, `loitering` in purple).
  3. Create a Met-Ocean Telemetry card displaying wind speed/direction, current speed/direction, and data source.
  4. Add a "Download Forensic Report" button that triggers the PDF export endpoint.
- **AI Prompt:**
  > "In frontend/templates/results.html, design a responsive Bootstrap 5 suspect leaderboard table. Format composite score as a percentage bar, display badges for each anomaly, and include an expandable row showing breakdown scores (proximity, temporal, behavioral)."

---

### Frontend Developer 3: Upload Wizard & Pipeline Stepper
- **Directory:** `frontend/`
- **Key Tasks:**
  1. Build a drag-and-drop file upload zone for SAR imagery (.png, .jpg, .tif) with file size validation.
  2. Add collapsible inputs for optional bounding-box coordinates and manual wind/current overrides.
  3. Implement a live 4-stage stepper (Detection -> Drift Hindcast -> AIS Scoring -> Complete) that polls `/api/v1/pipeline/<run_id>/status/` every 2 seconds until finished, then redirects to the results page.
  4. Display friendly error messages when non-SAR images are rejected by the Out-of-Domain safeguard gate.
- **AI Prompt:**
  > "In frontend/templates/upload.html, write a clean JavaScript submission handler that uploads the SAR image via fetch to /api/v1/pipeline/run/, receives the job id, displays a 4-step animated progress bar, polls /api/v1/pipeline/<run_id>/status/ every 2 seconds, and redirects to /results/<run_id>/ upon completion."

---

### AI / ML Engineer: Model Upgrades & False Positive Filtering
- **Directory:** `ai_model/`
- **Key Tasks:**
  1. When new trained weights arrive, place them in `ai_model/weights/<new_model>/` and validate them using `python backend/manage.py validate_model`.
  2. Implement a look-alike discrimination filter: check local SAR wind speed (if < 3 m/s, sea is calm and can produce false positive low-backscatter patches) and calculate texture roughness (GLCM).
  3. Implement Bonn Agreement thickness heuristics to estimate total oil volume in cubic meters (m³) from polygon surface area.
- **AI Prompt:**
  > "In backend/apps/detection/postprocessing.py, create a function `estimate_spill_volume(area_sq_km, appearance_code='rainbow')` that calculates minimum and maximum estimated oil volume in cubic meters using Bonn Agreement thickness classifications."

---

## 7. Local Setup Guide (One Command)

### Step 1: Run the Automated Setup Script
```bash
chmod +x setup.sh
./setup.sh
```

### Step 2: Start the Celery Worker (Terminal 1)
```bash
source .venv/bin/activate
cd backend
celery -A config worker -Q detection_queue,drift_queue,ais_queue,default -c 2 -l INFO
```

### Step 3: Start the Web Server (Terminal 2)
```bash
source .venv/bin/activate
cd backend
python manage.py runserver 0.0.0.0:8000
```

### Step 4: Open Your Browser
- Web Interface: [http://localhost:8000/](http://localhost:8000/)
- Interactive API Documentation: [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
- Django Admin: [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

## 8. Instructions for AI Coding Assistants

If you are an AI assistant (Cursor, Claude Code, Copilot, Antigravity) working on this codebase:

1. **Zero Emojis:** Do not output emojis anywhere in code, markdown, docstrings, commit messages, or templates.
2. **Deterministic Physics:** Preserving the Lagrangian advection equation: `V_drift = V_current + 0.03 * V_wind`.
3. **No Breaking Model Hot-Swap:** Always keep `ModelManager` decoupled from weight paths via `settings.MODEL_CHECKPOINT_PATH`. Always preserve the baseline fallback mechanism.
4. **Georeference Enforcement:** Never bypass the Georeference Gate (Layer 3). Plain pixel images must not flow into AIS scoring without valid geographic bounds.
5. **Run Tests Before Committing:** Run `pytest backend/` to ensure all 13 existing unit and integration tests continue to pass.
