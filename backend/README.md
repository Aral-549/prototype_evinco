# Backend Subsystem (Django REST & Celery)
### MarSlick | SIH Problem Statement ID: 26143

The backend provides the asynchronous orchestration, RESTful APIs, and database persistence for the oil spill detection and vessel attribution engine.

---

## Directory Architecture

```
backend/
├── apps/
│   ├── detection/      # SAR image ingestion, sliding tile slicing, U-Net inference, polygonization
│   ├── drift/          # Lagrangian hydrodynamic advection, Open-Meteo integration, caching
│   ├── ais/            # MarineCadastre AIS CSV parser, vectorized Haversine scorer, anomaly detection
│   └── pipeline/       # Celery task orchestrator, state machine, REST API endpoints, Swagger schema
├── config/             # Django settings, Celery configuration, URL routing, CORS, logging
├── tests/              # 13 automated unit and integration tests
├── manage.py           # Django management CLI
├── requirements.txt    # Python package dependencies
├── pytest.ini          # Pytest configuration
└── Dockerfile          # Container specification
```

---

## Running Backend Services

### 1. Start Celery Asynchronous Worker
```bash
# From repository root
source .venv/bin/activate
cd backend
celery -A config worker -Q detection_queue,drift_queue,ais_queue,default -c 2 -l INFO
```

### 2. Start Django REST API Server
```bash
# From repository root
source .venv/bin/activate
cd backend
python manage.py runserver 0.0.0.0:8000
```

### 3. Run Automated Tests
```bash
cd backend
pytest
```

---

## Interactive API Documentation

- **Swagger UI:** [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
- **OpenAPI 3.0 Schema:** [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/)
- **Django Admin Console:** [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

## Assigned Backend Roles

- **Backend Dev 1 (API, Reports, Deployment):** API pagination, PDF forensic incident report generation (`PipelineReportPDFView`), and Docker deployment.
- **Backend Dev 2 (Hydrodynamics & Met-Ocean):** Historical weather reanalysis (Copernicus CMEMS/HYCOM), oil weathering physics (evaporation loss), and OpenDrift engine integration.
- **Backend Dev 3 (AIS Telemetry & PostGIS):** Spatial query scaling with PostGIS (`ST_DWithin`), live AIS stream consumer, and SAR bright-spot dark vessel detection.
