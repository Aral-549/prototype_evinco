# MarSlick: Autonomous Satellite Oil Spill Detection & AIS Forensic Attribution Platform
### Smart India Hackathon (SIH 2026) • Problem Statement: 26143
**Category:** Marine Surveillance, Space Applications, & National Maritime Security  
**Beneficiary Agencies:** Indian Coast Guard (ICG), Directorate General of Shipping (DGS), National Technical Research Organisation (NTRO)  
**Team:** Evinco  

---

## 🌐 Live Cloud Deployment (Try It Live)

The platform is deployed 24/7 on an Azure cloud instance with SSL encryption and full mobile/desktop responsiveness:

* **Live Interactive Console:** [https://evinco-sih.centralindia.cloudapp.azure.com/](https://evinco-sih.centralindia.cloudapp.azure.com/)
* **Interactive OpenAPI / Swagger Documentation:** [https://evinco-sih.centralindia.cloudapp.azure.com/api/docs/](https://evinco-sih.centralindia.cloudapp.azure.com/api/docs/)
* **Pre-Seeded Evidentiary Dossiers:** Click on any case on the live home dashboard to inspect end-to-end evidence, Monte Carlo particle clouds, and vessel attribution rankings.

---

## 1. The Real-World Problem: The "Midnight Bilge Dump"

Every night across the Indian Ocean, Arabian Sea, and Bay of Bengal, commercial tankers and cargo carriers illegally discharge toxic oily bilge water and tank washings into international and territorial waters. They do this under cover of darkness to evade port reception fees that run into tens of thousands of dollars.

When maritime authorities detect a slick on a satellite radar image days later, two physical realities make identifying the culprit near impossible:
1. **The Ocean Never Stands Still:** Driven by surface winds and ocean currents, the slick has drifted 15 to 40 nautical miles away from where the ship dumped it. Its shape has smeared, diffused, and fragmented.
2. **The Sea is Crowded:** Hundreds of commercial vessels cross the same shipping lane every 24 hours. By the time a coastal surveillance team finishes cross-referencing satellite files with manual GIS ship logs 48 to 72 hours later, the offending ship is already docking in a foreign jurisdiction.
3. **Legal Defensibility:** Most AI demos draw a red box around dark pixels. But in maritime law, accusing a shipping conglomerate requires admissible evidence: proving the dark patch wasn't a natural algae bloom or wind shadow, reconstructing the exact time and coordinate of release, and demonstrating joint spatio-temporal coincidence with a vessel.

**MarSlick solves the entire pipeline in under 10 seconds.** It ingests raw SAR radar scenes, screens candidates against fluid mechanics principles, runs a 500-particle Monte Carlo backward drift simulation through met-ocean fields, computes joint Bayesian vessel attribution from AIS transponder logs, seals the findings in a SHA-256 cryptographic manifest, and generates a filable evidentiary dossier.

---

## 2. System Architecture & End-to-End Pipeline

```
  [ Sentinel-1 SAR Scene ] ────────► [ Sliding-Tile Inference (256x256, 32px overlap) ]
                                                       │
                                                       ▼
                                         [ Dual-Backbone Segmentation ]
                                       • Custom 4-Stage ResNet U-Net (Dice: 0.8018)
                                       • SegFormer-B0 Transformer Ensemble
                                                       │
                                                       ▼
                                      [ Physics Look-Alike Screening ]
                                       • Speckle Damping (CV ratio)
                                       • Wind Gate (>3 m/s Bragg threshold)
                                       • Gradient & Boundary Sharpness
                                                       │
                           ┌───────────────────────────┴───────────────────────────┐
                           ▼                                                       ▼
                   [ REJECTED: Decoy ]                                     [ ACCEPTED: Mineral Oil ]
                 (Calm zone / biogenic)                                            │
                                                                                   ▼
                                                                     [ Monte Carlo Drift Hindcast ]
                                                                      500 particles backward-advected:
                                                                      V_drift = V_curr + 0.03*V_wind
                                                                      Hourly Open-Meteo fields + Ekman drift
                                                                                   │
                                                                                   ▼
                                                                     [ Spatio-Temporal AIS Match ]
                                                                      Joint Bayesian likelihood over space & time
                                                                      + Dark vessel transponder blackout detection
                                                                                   │
                                                                                   ▼
                                                                     [ Evidentiary Dossier & Audit ]
                                                                      • SHA-256 Sealed Evidence Manifest
                                                                      • Monte Carlo 50% & 90% Confidence Hulls
                                                                      • Court-Admissible PDF Report Generation
```

---

## 3. What We Actually Built (The Technical Breakthroughs)

### A. Dual-Backbone AI Segmentation & Out-of-Domain Guard
* **Pixel-Level Segmentation:** Deploys a custom 4-stage U-Net baseline paired with a SegFormer-B0 (MiT-B0 hierarchical encoder with an all-MLP decoder) operating in an ensemble mode.
* **SAR Domain Gate:** Neural networks trained on SAR will hallucinate slicks if given optical satellite imagery, aerial photos, or land surfaces. Our pipeline implements an automated input verification gate that validates radar speckle distribution (Rayleigh / Gamma backscatter statistics) before inference begins. Non-SAR imagery is instantly rejected.

### B. Physical Screening: Separating Oil from "Look-Alikes"
The single biggest failure point of commercial oil-spill tools is false positives caused by natural phenomena: wind-calm zones, biogenic algal films, rain cells, and land shadows. They all appear dark on radar because capillary waves are dampened.
* **Speckle Damping (Coefficient of Variation Ratio):** The decisive physics differentiator. A mineral oil slick damps high-frequency surface capillary waves, altering the radar speckle texture. A calm zone reduces radar return but leaves the underlying speckle statistics intact.
* **Bragg Wind Boundary (3.0 m/s Gate):** Below ~3.0 m/s wind speed, the ocean surface is naturally mirror-smooth and cannot backscatter radar pulses. Slicks cannot be reliably differentiated from calm water at these speeds. Rather than hallucinating, the model reports a low-confidence warning grounded in physical limits.

### C. 500-Particle Monte Carlo Drift Hindcast
Instead of drawing a naive straight line backward, MarSlick reconstructs the release point probabilistically:
* **Physics Engine:** Integrates hourly met-ocean surface current vectors and 10-meter wind fields.
* **Stochastic Ensemble:** Releases 500 virtual particles advected backward in time. Each particle samples from empirical distributions of windage factors (2.5% – 3.5%), turbulent diffusion, and Coriolis/Ekman drift angles.
* **Uncertainty Contours:** Fits 50% and 90% confidence hulls around the particle cloud. This gives maritime investigators a true probability density of the spill origin, not an arbitrary single coordinate.

### D. Joint Spatio-Temporal AIS Vessel Attribution
* **Joint Coincidence:** A vessel 1 km away from the spill 12 hours before or after the release point has zero attribution score. The likelihood is joint in 4D spacetime ($x, y, z, t$).
* **Dark Vessel Anomaly Detection (`dark_vessel_gap`):** Tankers committing environmental crimes frequently switch off their AIS transponders ("going dark") before discharging. The pipeline scans for sudden gap anomalies in transponder broadcasts and flags vessels whose dead-reckoning trajectory crosses the spill release cone during a blackout.

### E. The Courage to Say "Insufficient Evidence"
Forensic tools must never guess. If the radar data, drift ensemble, or AIS coverage does not produce statistically significant attribution, MarSlick deliberately concludes **`insufficient_evidence`**. This prevents wrongful impoundment of innocent vessels and gives maritime prosecutors ironclad credibility in court.

---

## 4. What Is in the Generated Forensic Reports?

When an analysis concludes, the platform seals the investigation and generates a **Court-Admissible Evidentiary Dossier** (available on the web UI and downloadable as a sealed PDF at `/api/v1/pipeline/<case_id>/report/`):

1. **Chain of Custody & Integrity Seal:**
   * Unique Case UUID and UTC timestamp of processing.
   * Cryptographic SHA-256 hash of the input SAR image, model weights, met-ocean weather cache, and AIS records. Any byte-level modification invalidates the dossier.
   * Submitter credential fingerprint conforming to Section 65B of the Indian Evidence Act.
2. **Detection & Look-Alike Evidence:**
   * Raw SAR backscatter tile, model segmentation mask, and polygon centroid.
   * Log-odds breakdown of physical tests (backscatter damping, speckle CV ratio, edge gradient, wind gate).
3. **Drift Ensemble Coordinates:**
   * Estimated release time window.
   * Latitude and longitude of the primary origin centroid.
   * 50% and 90% spatial dispersion radii (in kilometers).
4. **Attribution Suspect Leaderboard:**
   * Ranked table of vessels in the operational area.
   * Name, MMSI, IMO, vessel flag, and vessel type.
   * Closest Point of Approach (CPA) distance in kilometers and time difference.
   * Posterior attribution probability ($p$).
   * Behavioral red flags (`dark_vessel_gap`, `loitering`, `speed_anomaly`).
5. **Robustness & Self-Audit:**
   * Automated perturbation testing: runs 32 sensitivity scenarios varying wind and current vectors by $\pm 15\%$. If the top suspect changes under minor perturbation, the case is flagged as unstable.

---

## 5. Technology Stack

| Tier | Technologies | Justification |
|---|---|---|
| **AI & Computer Vision** | PyTorch, Torchvision, SegFormer, OpenCV | CPU-optimized PyTorch inference (<2s runtime per tile). |
| **Backend & APIs** | Python 3.12, Django 5, Django REST Framework | Enterprise-grade ORM, clean serializer architecture, hermetic testability. |
| **Pipeline Architecture** | Synchronous In-Process Execution (`run_pipeline`) | Eliminates fragile Redis/Celery broker requirements; runs anywhere hermetically. |
| **Frontend UI / UX** | Next.js 15, React 19, TypeScript, Tailwind CSS, Framer Motion, Leaflet.js | High-performance reactive geospatial GIS interface with dark-mode radar styling. |
| **Data & Met-Ocean** | Open-Meteo Marine API, MarineCadastre AIS, NumPy, Pandas | Real-world surface currents, 10m wind fields, and vectorized Haversine indexing. |
| **Infrastructure** | Ubuntu Linux, Nginx reverse proxy, Let's Encrypt SSL, Systemd | Hosted 24/7 on Azure Cloud with automatic service recovery. |

---

## 6. Verification: 142 Automated Tests (100% Hermetic)

The repository includes a comprehensive test suite that validates every layer of the system:
* **Neural Network Weights & Slicing:** Tests tile coordinate math, seam handling, and polygon extraction.
* **Physics Formulations:** Validates Lagrangian backward advection equations, windage scaling, and Coriolis deflection against synthetic baselines.
* **Forensic Evidence Immutability:** Tests SHA-256 hash validation and ensures altered payloads fail verification.
* **Zero Network Dependency:** The entire suite runs without internet, databases, or third-party services.

Run the tests locally:
```bash
# Activate virtual environment
source .venv/bin/activate

# Execute pytest
pytest backend
```
**Result:** `142 passed, 2 xfailed` in **3.84s** (the 2 `xfailed` are intentional negative controls documenting historical Gaussian noise edge cases; see `BUGLOG.md`).

---

## 7. Zero-Friction Local Setup (Run It on Your Machine)

If you prefer testing the repository locally rather than on our live cloud server, you can set it up in 3 simple steps:

### Prerequisites
* Python 3.10+ (tested on Python 3.11 & 3.12)
* Node.js 18+ & npm
* Git

### Step 1: Clone the Repository
```bash
git clone https://github.com/Aral-549/prototype_evinco.git
cd prototype_evinco
```

### Step 2: Setup and Start the Backend
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate

# Install dependencies (CPU-optimized PyTorch installed automatically)
pip install --upgrade pip
pip install -r backend/requirements.txt

# Run migrations and seed the two deterministic demo cases
python backend/manage.py migrate
python backend/manage.py seed_demo

# Start the Django API server on port 8000
python backend/manage.py runserver 0.0.0.0:8000
```

### Step 3: Start the Next.js Frontend
In a new terminal window:
```bash
cd prototype_evinco/frontend
npm install
npm run dev
```

Open your browser at **`http://localhost:3000/`**.  
The console will load immediately with the pre-seeded demo cases and live SAR upload tool!
API documentation is browsable at **`http://localhost:8000/api/docs/`**.

---

## 8. Repository Structure

```
prototype_evinco/
├── backend/                      # Django REST API & Forensic Engine
│   ├── apps/
│   │   ├── ais/                  # AIS tracking, spatial indexing, anomaly detection
│   │   ├── detection/            # U-Net & SegFormer inference, look-alike physics
│   │   ├── drift/                # Lagrangian Monte Carlo backward advection
│   │   └── pipeline/             # Pipeline orchestrator, dossier, PDF report generator
│   ├── config/                   # Django settings, URLs, API authentication
│   └── tests/                    # 142 hermetic automated unit & integration tests
├── frontend/                     # Next.js 15 Geospatial UI
│   ├── app/                      # App router (Home console, Case dossier view)
│   ├── components/               # Leaflet map, radar upload wizard, forensic panels
│   └── services/                 # Strongly-typed API client
├── ai_model/                     # Pre-trained deep learning weights & calibration scenes
│   ├── weights/                  # Checked-in U-Net and SegFormer model checkpoints
│   └── calibration_data/         # Calibrated radar backscatter benchmark scenes
├── deploy_azure.sh               # Automated Azure VM production deployment script
├── setup_ssl_and_routes.sh       # Multi-project SSL Nginx reverse proxy configuration
├── BUGLOG.md                     # Engineering hardening log: 19 real defects found & resolved
└── README.md                     # This documentation
```

---

## 9. Hackathon Submission Summary

* **Project:** MarSlick (PS 26143)
* **Team Name:** Evinco
* **Live Online Demo:** [https://evinco-sih.centralindia.cloudapp.azure.com/](https://evinco-sih.centralindia.cloudapp.azure.com/)
* **Contact Email:** `shaik2.mitmpl2025@learner.manipal.edu`
