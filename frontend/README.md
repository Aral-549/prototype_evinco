# Frontend Subsystem (Web GIS & Dashboards)
### MarSlick | SIH Problem Statement ID: 26143

The frontend provides the interactive geospatial map, suspect vessel ranking leaderboard, and the SAR image upload wizard.

---

## Directory Architecture

```
frontend/
├── templates/                  # Server-rendered HTML templates (Bootstrap 5 & Leaflet.js)
│   ├── base.html               # Common layout, Leaflet CDN, dark theme
│   ├── upload.html             # SAR upload form with parameter controls & recent runs table
│   └── results.html            # Interactive Leaflet map, slick polygons, drift lines, suspect leaderboard
├── static/                     # CSS stylesheets, JavaScript plugins, custom map markers
├── FRONTEND_INTEGRATION.md     # TypeScript interfaces & API contracts for React / Next.js
└── README.md                   # Frontend developer instructions
```

---

## Working Prototype Interface

The built-in prototype interface is served directly by the backend at:
- **Upload Wizard:** [http://localhost:8000/](http://localhost:8000/)
- **Sample Results Dashboard:** [http://localhost:8000/results/<run_id>/](http://localhost:8000/results/<run_id>/)

---

## Building a Dedicated React / Next.js App

If building a modern standalone frontend using Next.js, Vite, or React:
1. Review the TypeScript interfaces and API schemas in [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md).
2. CORS is already enabled for `http://localhost:3000` (Next.js) and `http://localhost:5173` (Vite).
3. Connect your HTTP client (Axios or Fetch) to `http://localhost:8000/api/v1/`.

---

## Assigned Frontend Roles

- **Frontend Dev 1 (Geospatial Map Canvas):** Leaflet / Mapbox GL layers for oil slick GeoJSON polygons, dashed drift hindcast lines, origin markers, and suspect vessel tracks.
- **Frontend Dev 2 (Suspect Dossier & Analytics):** Ranked vessel table, anomaly badges (`ais_gap`, `speed_change`, `loitering`), score breakdown charts, and PDF download trigger.
- **Frontend Dev 3 (Upload Wizard & Pipeline Stepper):** Drag-and-drop file uploader, bounding box coordinate selector, and live 4-stage progress stepper polling the API.
