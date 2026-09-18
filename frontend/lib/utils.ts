import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number to a fixed precision, rendering null/undefined as an em dash. */
export function num(v: number | null | undefined, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

/** Percentage with no decimals, e.g. 0.7233 -> "72%". */
export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/** Signed decimal degrees to a maritime-style coordinate, e.g. "19.0657° N". */
export function coord(v: number | null | undefined, axis: "lat" | "lon"): string {
  if (v === null || v === undefined) return "—";
  const hemi = axis === "lat" ? (v >= 0 ? "N" : "S") : v >= 0 ? "E" : "W";
  return `${Math.abs(v).toFixed(4)}° ${hemi}`;
}

/** Shorten a 64-char digest for display without losing its recognisability. */
export function shortHash(h: string | null | undefined, head = 10, tail = 6): string {
  if (!h) return "—";
  if (h.length <= head + tail + 1) return h;
  return `${h.slice(0, head)}…${h.slice(-tail)}`;
}

export function formatUTC(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms && ms !== 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
