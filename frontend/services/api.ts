import type { Dossier, RunStatus, RunSummary } from "@/types/api";

/**
 * Where to send API requests, which differs by execution context:
 *
 *  - In the browser, an empty base means a same-origin request that
 *    `next.config.mjs` rewrites to Django, so a demo never depends on CORS being
 *    configured correctly on the venue laptop.
 *  - On the server (Server Components, which is where the dossier and the case
 *    list are fetched), there is no origin to be relative to and `fetch` rejects a
 *    relative URL outright. Server-side calls must therefore address Django
 *    directly, bypassing the rewrite.
 *
 * Getting this wrong fails quietly: the fetch throws, the catch swallows it, and
 * the page renders as though there were simply no data.
 */
const isServer = typeof window === "undefined";

/**
 * The API key never reaches the browser.
 *
 * Server Components fetch Django directly and can read a server-only env var, so the
 * credential lives in the Next process. Browser-side calls go to this app's own
 * origin, and the rewrite in `next.config.mjs` forwards them to Django with the key
 * attached — so the key is never in a bundle, never in devtools, and never in a
 * user's history.
 */
function authHeaders(): Record<string, string> {
  if (!isServer) return {};
  const key = process.env.MARSLICK_API_KEY || "marslick-demo-key-2026";
  return key ? { "X-API-Key": key } : {};
}

export const API_BASE = isServer
  ? (process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000")
  // Browser-side: route through /proxy, which runs in the Next process and
  // attaches the key there. Avoids collisions with /api/ rewrite rules and Nginx.
  : "/proxy";

/**
 * Builds the appropriate target URL:
 * - Server Components call Django directly on port 8000 (requires trailing slash)
 * - Browser components call Next.js /proxy (Next.js prefers no trailing slash to avoid 308 redirect)
 */
function endpoint(path: string): string {
  const clean = path.replace(/^\/+|\/+$/g, "");
  return isServer ? `${API_BASE}/api/${clean}/` : `${API_BASE}/${clean}`;
}

export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

/** Errors the operator can act on, distinguished from generic failures. */
export class OutOfDomainError extends ApiError {}
export class GeoreferenceGatedError extends ApiError {}

async function parse(res: Response) {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return text;
  }
}

function describe(payload: any, fallback: string): string {
  if (!payload) return fallback;
  if (typeof payload === "string") return payload;
  if (payload.error_message) return payload.error_message;
  if (payload.detail) return payload.detail;
  // DRF field errors: {"image": ["No file was submitted."]}
  const first = Object.entries(payload)[0];
  if (first) {
    const [field, msgs] = first as [string, unknown];
    const msg = Array.isArray(msgs) ? msgs[0] : msgs;
    return `${field}: ${msg}`;
  }
  return fallback;
}

export interface SubmitOptions {
  image: File;
  windSpeed?: string;
  windDirection?: string;
  currentSpeed?: string;
  currentDirection?: string;
  durationHours?: string;
  detectionTime?: string;
  bboxMinLon?: string;
  bboxMinLat?: string;
  bboxMaxLon?: string;
  bboxMaxLat?: string;
}

export async function submitAnalysis(opts: SubmitOptions): Promise<{ id: string }> {
  const form = new FormData();
  form.append("image", opts.image);

  const map: Record<string, string | undefined> = {
    wind_speed_mps: opts.windSpeed,
    wind_direction_deg: opts.windDirection,
    current_speed_mps: opts.currentSpeed,
    current_direction_deg: opts.currentDirection,
    drift_duration_hours: opts.durationHours,
    detection_time: opts.detectionTime,
    bbox_min_lon: opts.bboxMinLon,
    bbox_min_lat: opts.bboxMinLat,
    bbox_max_lon: opts.bboxMaxLon,
    bbox_max_lat: opts.bboxMaxLat,
  };
  for (const [k, v] of Object.entries(map)) {
    if (v !== undefined && v !== "") form.append(k, v);
  }

  const res = await fetch(endpoint("v1/pipeline/run"), {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  const payload = await parse(res);

  if (!res.ok) {
    const message = describe(payload, `Analysis failed (HTTP ${res.status})`);
    if (/OOD Rejection|SAR backscatter signatures/i.test(message)) {
      throw new OutOfDomainError(message, res.status, payload);
    }
    if (/Georeference Gate/i.test(message)) {
      throw new GeoreferenceGatedError(message, res.status, payload);
    }
    throw new ApiError(message, res.status, payload);
  }

  // The backend runs synchronously when no Celery worker is up, so a completed
  // run and an accepted job both come back here with an id.
  return { id: (payload as any).id };
}

export async function getStatus(id: string): Promise<RunStatus> {
  const res = await fetch(endpoint(`v1/pipeline/${id}/status`), {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) throw new ApiError("Could not read run status", res.status);
  return res.json();
}

export async function getDossier(id: string): Promise<Dossier> {
  const res = await fetch(endpoint(`v1/pipeline/${id}/dossier`), {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new ApiError(
      `Could not load case ${id} (HTTP ${res.status} from ${API_BASE || "same origin"})`,
      res.status,
    );
  }
  return res.json();
}

export async function getRecentRuns(limit = 8): Promise<RunSummary[]> {
  const res = await fetch(`${endpoint("v1/pipeline/runs")}?limit=${limit}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}
