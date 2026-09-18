/** Types mirroring `backend/apps/pipeline/dossier.py`. */

export type Verdict = "strong" | "probable" | "weak" | "insufficient";
export type LookAlikeVerdict = "probable_oil" | "ambiguous" | "probable_lookalike";

export interface VolumeEstimate {
  volume_m3_min: number;
  volume_m3_max: number;
  appearance_code: string;
  thickness_um_min: number;
  thickness_um_max: number;
  caveat: string;
}

export interface TrajectoryPoint {
  lat: number;
  lon: number;
  time: string;
}

export interface Particle {
  lat: number;
  lon: number;
  time: string;
  windage: number;
}

export interface GeoJSONPolygon {
  type: "Polygon";
  coordinates: number[][][];
}

export interface DriftBlock {
  id: number;
  engine_used: string;
  origin_lat: number;
  origin_lon: number;
  origin_time: string | null;
  origin_uncertainty_km: number | null;
  radius_50_km: number | null;
  radius_90_km: number | null;
  confidence_polygon_50: GeoJSONPolygon | Record<string, never>;
  confidence_polygon_90: GeoJSONPolygon | Record<string, never>;
  particles: Particle[];
  n_particles: number;
  ensemble_seed: number;
  hindcast_trajectory: TrajectoryPoint[];
  forecast_trajectory: TrajectoryPoint[];
  evaporated_fraction: number | null;
  weathering_warning: string;
  metocean_source: string;
  metocean_degraded_steps: number;
  wind_speed_mps: number;
  wind_direction_deg: number;
  current_speed_mps: number;
  current_direction_deg: number;
  duration_hours: number;
}

export interface Region {
  id: number;
  polygon_geojson: GeoJSONPolygon;
  centroid_lat: number | null;
  centroid_lon: number | null;
  area_sq_km: number | null;
  confidence: number;
  oil_probability: number | null;
  lookalike_verdict: LookAlikeVerdict | "";
  lookalike_features: Record<string, number>;
  lookalike_contributions: Record<string, number>;
  lookalike_notes: string[];
  shape_complexity: number | null;
  volume_estimate: VolumeEstimate | Record<string, never>;
  drift: DriftBlock | null;
}

export interface TrackPoint {
  lat: number;
  lon: number;
  time: string;
  speed_knots: number | null;
}

export interface Suspect {
  track: TrackPoint[];
  rank: number;
  mmsi: string;
  vessel_name: string;
  vessel_type: string;
  flag: string;
  posterior: number | null;
  verdict: Verdict | "";
  spatiotemporal_likelihood: number | null;
  behavioural_factor: number | null;
  cpa_km: number | null;
  cpa_time: string | null;
  anomalies: string[];
  explanation: string[];
  legacy_composite_score: number;
  legacy_proximity_score: number;
  legacy_temporal_score: number;
  legacy_behavioral_score: number;
  integrity_plausible: boolean;
  integrity_flags: IntegrityFlag[];
  max_implied_speed_kn: number | null;
}

export interface BreakingPoint {
  parameter: string;
  value: string;
  baseline_value: string;
  new_top: string;
  note: string;
}

export interface Robustness {
  stability?: number;
  verdict_stability?: number;
  posterior_min?: number;
  posterior_median?: number;
  posterior_max?: number;
  breaking_points?: BreakingPoint[];
  most_influential?: string;
  scenarios_run?: number;
  assessment?: "robust" | "conditional" | "fragile";
  narrative?: string[];
  baseline_mmsi?: string;
  error?: string;
}

export interface IntegrityFlag {
  code: string;
  severity: number;
  detail: string;
}

export interface Dossier {
  run: {
    id: string;
    status: string;
    stage: string;
    stage_durations_ms: Record<string, number>;
    created_at: string | null;
    completed_at: string | null;
    is_georeferenced: boolean;
    error_message: string;
    spills_detected: number;
    suspects_ranked: number;
    regions_rejected_as_lookalike: number;
    metocean_source: string;
    drift_duration_hours: number;
    total_duration_ms: number;
  };
  model: {
    name: string;
    version: string;
    checkpoint_id: string;
    dice_score: number | null;
    iou_score: number | null;
    output_activation: string;
    is_fallback: boolean;
    ensemble_members: string[];
    ensemble_size: number;
  };
  attribution: {
    summary: { conclusion?: string; headline?: string; unknown_posterior?: number };
    unknown_vessel_posterior: number | null;
    stale?: boolean;
    stale_reason?: string;
  };
  chain_of_custody: Record<string, any>;
  robustness: Robustness;
  imagery?: {
    uploaded_image: string | null;
    result_mask: string | null;
    probability_map: string | null;
    width: number;
    height: number;
    processing_time_ms: number | null;
  };
  regions: Region[];
  suspects: Suspect[];
}

export interface RunStatus {
  id: string;
  status: string;
  stage: string;
  stage_durations_ms: Record<string, number>;
  spills_detected: number;
  suspects_ranked: number;
  regions_rejected_as_lookalike: number;
  error_message: string;
  is_georeferenced: boolean;
}

export interface RunSummary {
  id: string;
  status: string;
  stage: string;
  created_at: string | null;
  spills_detected: number;
  suspects_ranked: number;
  is_georeferenced: boolean;
  conclusion: string | null;
  manifest_sha256: string;
}
