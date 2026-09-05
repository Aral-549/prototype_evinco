# Frontend Integration Guide & API Contracts
### For Next.js, React (Vite), and Geospatial UI Engineers

This guide provides everything the frontend team needs to build, connect, and visualize the Oil Spill & AIS Identification backend.

---

## Connection Details & CORS

- **API Base URL:** `http://localhost:8000`
- **Interactive Swagger Docs:** `http://localhost:8000/api/docs/`
- **OpenAPI 3.0 Schema Spec:** `http://localhost:8000/api/schema/`
- **CORS Allowed Origins:**
  - `http://localhost:3000` (Next.js default)
  - `http://localhost:5173` (Vite / React default)
  - `http://127.0.0.1:3000` & `http://127.0.0.1:5173`
- Credentials / Cookies are supported (`access-control-allow-credentials: true`).

---

## [Pending] Core API Endpoints

| Method | Endpoint | Description | Payload / Response |
|---|---|---|---|
| `POST` | `/api/v1/pipeline/run/` | Trigger full end-to-end analysis | `multipart/form-data` -> Returns `201 Created` with run ID |
| `GET` | `/api/v1/pipeline/{id}/status/` | Fast polling endpoint for progress bar | Returns `{ id, status, spills_detected, suspects_ranked, stage_breakdown }` |
| `GET` | `/api/v1/pipeline/{id}/` | Full results (polygons, drift, suspects) | Complete intelligence dossier JSON |
| `GET` | `/api/v1/detection/{job_id}/mask/` | Binary segmentation mask image | `image/png` |
| `GET` | `/api/v1/ais/vessels/{mmsi}/track/` | Historical track coordinates for suspect vessel | Trajectory points array `[{ lat, lon, timestamp }]` |

---

## TypeScript Interface Definitions

Copy and paste these directly into your frontend project (`types/api.ts`):

```typescript
export type PipelineStatus = 
  | 'pending'
  | 'detecting'
  | 'drifting'
  | 'scoring'
  | 'completed'
  | 'failed';

export type MetoceanSource = 
  | 'open-meteo'
  | 'manual_override'
  | 'default_fallback';

export interface StageBreakdown {
  detection_ms: number | null;
  drift_ms: number | null;
  scoring_ms: number | null;
}

export interface PipelineStatusResponse {
  id: string;
  status: PipelineStatus;
  error_message: string;
  spills_detected: number;
  suspects_ranked: number;
  stage_breakdown?: StageBreakdown;
}

export interface SpillRegion {
  id: number;
  polygon_geojson: {
    type: 'Polygon';
    coordinates: number[][][]; // GeoJSON format: [ [ [lon, lat], ... ] ]
  };
  centroid_lat: number;
  centroid_lon: number;
  area_sq_km: number;
  confidence: number;
}

export interface DriftTrajectoryPoint {
  lat: number;
  lon: number;
  time: string; // ISO-8601
}

export interface DriftResult {
  id: number;
  spill_region: number;
  engine_used: 'lagrangian' | 'opendrift';
  origin_lat: number;
  origin_lon: number;
  origin_time: string; // ISO-8601
  origin_uncertainty_km: number;
  hindcast_trajectory: DriftTrajectoryPoint[];
  forecast_trajectory: DriftTrajectoryPoint[];
  wind_speed_mps: number;
  wind_direction_deg: number;
  current_speed_mps: number;
  current_direction_deg: number;
  metocean_source: MetoceanSource;
  duration_hours: number;
}

export interface Vessel {
  mmsi: string;
  name: string;
  vessel_type: string;
  flag: string;
  length_m: number | null;
  width_m: number | null;
}

export interface SuspectScore {
  id: number;
  vessel: Vessel;
  rank: number;
  composite_score: number;
  proximity_score: number;
  temporal_score: number;
  behavioral_score: number;
  min_distance_km: number;
  closest_time: string;
  anomalies_detected: ('speed_change' | 'ais_gap' | 'loitering')[];
}

export interface PipelineRunResponse {
  id: string;
  status: PipelineStatus;
  error_message: string;
  created_at: string;
  completed_at: string | null;
  spills_detected: number;
  suspects_ranked: number;
  wind_speed_mps: number;
  wind_direction_deg: number;
  current_speed_mps: number;
  current_direction_deg: number;
  drift_duration_hours: number;
  metocean_source: MetoceanSource;
  detection_job: {
    id: string;
    uploaded_image: string;
    result_mask: string | null;
    status: string;
    processing_time_ms: number;
    image_width: number;
    image_height: number;
    spill_regions: SpillRegion[];
  } | null;
  drift_results: DriftResult[];
  suspects: SuspectScore[];
}
```

---

## API Client & Polling Implementation (React Example)

```typescript
// services/pipelineService.ts
const BASE_URL = 'http://localhost:8000';

export async function submitAnalysis(formData: FormData): Promise<string> {
  const response = await fetch(`${BASE_URL}/api/v1/pipeline/run/`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.error || errorData.detail || 'Analysis request rejected');
  }

  const data = await response.json();
  return data.id; // Returns pipeline run UUID
}

export async function pollUntilComplete(
  runId: string, 
  onProgress?: (status: string) => void
): Promise<PipelineRunResponse> {
  const pollInterval = 1000; // 1 second

  while (true) {
    const statusRes = await fetch(`${BASE_URL}/api/v1/pipeline/${runId}/status/`);
    if (!statusRes.ok) throw new Error('Failed to query status');
    
    const statusData = await statusRes.json();
    if (onProgress) onProgress(statusData.status);

    if (statusData.status === 'completed') {
      const fullRes = await fetch(`${BASE_URL}/api/v1/pipeline/${runId}/`);
      return await fullRes.json();
    }

    if (statusData.status === 'failed') {
      throw new Error(statusData.error_message || 'Pipeline execution failed');
    }

    await new Promise(r => setTimeout(r, pollInterval));
  }
}
```

---

## Geospatial Map Integration (Leaflet Example)

```javascript
import L from 'leaflet';

export function renderAnalysisMap(mapInstance, analysisData) {
  // 1. Render Spill Polygons (Red)
  if (analysisData.detection_job?.spill_regions) {
    analysisData.detection_job.spill_regions.forEach(spill => {
      L.geoJSON(spill.polygon_geojson, {
        style: {
          color: '#ef4444',
          weight: 2,
          fillColor: '#dc2626',
          fillOpacity: 0.6,
        }
      }).bindPopup(`<b>Spill #${spill.id}</b><br>Area: ${spill.area_sq_km.toFixed(2)} km²<br>Confidence: ${(spill.confidence * 100).toFixed(1)}%`)
        .addTo(mapInstance);
    });
  }

  // 2. Render Drift Trajectories (Hindcast = Blue dashed, Forecast = Green dashed)
  analysisData.drift_results?.forEach(drift => {
    // Hindcast
    if (drift.hindcast_trajectory?.length) {
      const points = drift.hindcast_trajectory.map(p => [p.lat, p.lon]);
      L.polyline(points, {
        color: '#3b82f6',
        dashArray: '5, 10',
        weight: 3,
      }).bindPopup(`<b>Hindcast Advection Track</b><br>Met-Ocean: ${drift.metocean_source}`).addTo(mapInstance);
    }

    // Origin Estimate Marker
    L.circleMarker([drift.origin_lat, drift.origin_lon], {
      radius: 8,
      fillColor: '#f97316',
      color: '#fff',
      weight: 2,
      fillOpacity: 0.9,
    }).bindPopup(`<b>Estimated Spill Origin Point</b><br>Uncertainty: ±${drift.origin_uncertainty_km} km`).addTo(mapInstance);
  });

  // 3. Render Ranked Suspect Vessels (Vessel Icons with Rank)
  analysisData.suspects?.forEach(suspect => {
    const isTop1 = suspect.rank === 1;
    const marker = L.circleMarker([suspect.closest_lat || suspect.vessel.lat, suspect.closest_lon || suspect.vessel.lon], {
      radius: isTop1 ? 10 : 6,
      fillColor: isTop1 ? '#ef4444' : '#64748b',
      color: '#ffffff',
      weight: 2,
      fillOpacity: 0.9,
    });

    marker.bindPopup(`
      <div>
        <h6>Rank #${suspect.rank}: ${suspect.vessel.name}</h6>
        <p><b>MMSI:</b> ${suspect.vessel.mmsi}<br>
        <b>Type:</b> ${suspect.vessel.vessel_type}<br>
        <b>Composite Score:</b> ${(suspect.composite_score * 100).toFixed(1)}%<br>
        <b>Min Distance:</b> ${suspect.min_distance_km.toFixed(2)} km<br>
        <b>Anomalies:</b> ${suspect.anomalies_detected.join(', ') || 'None'}</p>
      </div>
    `).addTo(mapInstance);
  });
}
```

---

## Warning: Important Safeguard Responses

- **HTTP 400 Out-of-Domain Rejection:**
  If an optical photo, screenshot, or non-SAR image is uploaded, the backend rejects it with:
  ```json
  {
    "error": "Out-of-Domain image rejected: The uploaded image exhibits high-entropy optical or non-SAR characteristics."
  }
  ```
- **HTTP 400 Missing Georeference (Layer 3 Gate):**
  If a plain PNG/JPEG without georeferenced bounding box coordinates is uploaded, the backend rejects AIS correlation:
  ```json
  {
    "error": "Image is not georeferenced: Upload a valid GeoTIFF or supply bounding box coordinates (bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat)."
  }
  ```
