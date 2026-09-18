"use client";

import { useEffect, useRef, useState } from "react";
import type L from "leaflet";
import { Layers } from "lucide-react";
import type { Dossier } from "@/types/api";
import { cn } from "@/lib/utils";

type LayerKey = "slick" | "hindcast" | "forecast" | "ensemble" | "vessels";

const LAYER_LABELS: Record<LayerKey, string> = {
  slick: "Detected slick",
  hindcast: "Drift hindcast",
  forecast: "Forecast",
  ensemble: "Origin ensemble",
  vessels: "Vessel tracks",
};

const COLORS = {
  slick: "#e8a838",
  hindcast: "#5cc3e0",
  forecast: "#4ec9a0",
  ensemble: "#e8a838",
  suspect: "#e2603f",
  other: "#7a8699",
};

/**
 * The evidentiary map. Drawn in dependency order so the story reads outward from
 * the observation: the slick we saw, the path it drifted, where it came from, how
 * uncertain that is, and who was there.
 *
 * Leaflet is loaded dynamically because it touches `window` at import time.
 */
export function CaseMap({ dossier, height = 520 }: { dossier: Dossier; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const groupsRef = useRef<Partial<Record<LayerKey, L.LayerGroup>>>({});
  const [ready, setReady] = useState(false);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>({
    slick: true,
    hindcast: true,
    forecast: false,
    ensemble: true,
    vessels: true,
  });

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const leaflet = (await import("leaflet")).default;
      if (cancelled || !containerRef.current || mapRef.current) return;

      const map = leaflet.map(containerRef.current, {
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false,
      });
      mapRef.current = map;

      // Esri World Imagery: satellite basemap, no API key, and the right context for
      // a maritime case -- open water reads as open water rather than as blank canvas.
      // CARTO's dark tiles were used first but now return "API KEY REQUIRED"
      // watermarks, which rendered across the whole evidentiary map.
      leaflet
        .tileLayer(
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
          {
            attribution:
              "Imagery &copy; Esri, Maxar, Earthstar Geographics",
            maxZoom: 18,
          },
        )
        .addTo(map);

      // Place labels on top, so coastlines and ports stay identifiable.
      leaflet
        .tileLayer(
          "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
          { maxZoom: 18, opacity: 0.75 },
        )
        .addTo(map);

      const groups: Partial<Record<LayerKey, L.LayerGroup>> = {};
      (Object.keys(LAYER_LABELS) as LayerKey[]).forEach((k) => {
        groups[k] = leaflet.layerGroup().addTo(map);
      });
      groupsRef.current = groups;

      const bounds = leaflet.latLngBounds([]);

      for (const region of dossier.regions) {
        // ── Detected slick polygon ──────────────────────────────
        const rings = region.polygon_geojson?.coordinates ?? [];
        if (rings.length && region.centroid_lat !== null) {
          const latlngs = rings.map((ring) =>
            ring.map(([lon, lat]) => [lat, lon] as [number, number]),
          );
          const poly = leaflet
            .polygon(latlngs, {
              color: COLORS.slick,
              weight: 2,
              fillColor: COLORS.slick,
              fillOpacity: 0.22,
            })
            .bindPopup(
              `<b>Detected slick</b><br/>Area ${region.area_sq_km?.toFixed(1) ?? "—"} km²<br/>` +
                `Oil probability ${((region.oil_probability ?? 0) * 100).toFixed(0)}%<br/>` +
                `<span style="opacity:.7">${region.lookalike_verdict.replace(/_/g, " ")}</span>`,
            );
          poly.addTo(groups.slick!);
          bounds.extend(poly.getBounds());
        }

        const drift = region.drift;
        if (!drift) continue;

        // ── Backward hindcast: dashed, reads as reconstruction ──
        const hind = drift.hindcast_trajectory
          ?.filter((p) => p?.lat != null)
          .map((p) => [p.lat, p.lon] as [number, number]);
        if (hind?.length > 1) {
          const line = leaflet
            .polyline(hind, {
              color: COLORS.hindcast,
              weight: 2.5,
              dashArray: "6 6",
              opacity: 0.9,
            })
            .bindPopup("Backward drift hindcast (slick → origin)");
          line.addTo(groups.hindcast!);
          bounds.extend(line.getBounds());
        }

        const fore = drift.forecast_trajectory
          ?.filter((p) => p?.lat != null)
          .map((p) => [p.lat, p.lon] as [number, number]);
        if (fore?.length > 1) {
          leaflet
            .polyline(fore, { color: COLORS.forecast, weight: 2, opacity: 0.85 })
            .bindPopup("Forward forecast (landfall risk)")
            .addTo(groups.forecast!);
        }

        // ── Ensemble: 90% hull, 50% hull, particles, mean origin ──
        const hull = (poly: any, opacity: number, label: string) => {
          const ring = poly?.coordinates?.[0];
          if (!ring?.length) return;
          leaflet
            .polygon(
              ring.map(([lon, lat]: number[]) => [lat, lon] as [number, number]),
              {
                color: COLORS.ensemble,
                weight: 1,
                dashArray: "3 4",
                fillColor: COLORS.ensemble,
                fillOpacity: opacity,
              },
            )
            .bindPopup(label)
            .addTo(groups.ensemble!);
        };
        hull(drift.confidence_polygon_90, 0.07, "90% of release hypotheses");
        hull(drift.confidence_polygon_50, 0.13, "50% of release hypotheses");

        for (const p of drift.particles ?? []) {
          leaflet
            .circleMarker([p.lat, p.lon], {
              radius: 1.6,
              color: COLORS.ensemble,
              weight: 0,
              fillColor: COLORS.ensemble,
              fillOpacity: 0.5,
            })
            .addTo(groups.ensemble!);
        }

        const originMarker = leaflet
          .circleMarker([drift.origin_lat, drift.origin_lon], {
            radius: 7,
            color: "#ffffff",
            weight: 2,
            fillColor: COLORS.ensemble,
            fillOpacity: 1,
          })
          .bindPopup(
            `<b>Reconstructed release point</b><br/>` +
              `${drift.origin_lat.toFixed(4)}, ${drift.origin_lon.toFixed(4)}<br/>` +
              `50% within ${drift.radius_50_km?.toFixed(1)} km · 90% within ${drift.radius_90_km?.toFixed(1)} km<br/>` +
              `<span style="opacity:.7">${drift.n_particles} particles, seed ${drift.ensemble_seed}</span>`,
          );
        originMarker.addTo(groups.ensemble!);
        bounds.extend([drift.origin_lat, drift.origin_lon]);
      }

      // ── Vessel tracks: the prime suspect stands out, the rest recede ──
      dossier.suspects.forEach((s) => {
        const pts = (s.track ?? [])
          .filter((p) => p?.lat != null)
          .map((p) => [p.lat, p.lon] as [number, number]);
        if (!pts.length) return;

        const isPrime = s.rank === 1 && (s.posterior ?? 0) > 0.15;
        const color = isPrime ? COLORS.suspect : COLORS.other;

        if (pts.length > 1) {
          const line = leaflet.polyline(pts, {
            color,
            weight: isPrime ? 3 : 1.5,
            opacity: isPrime ? 0.95 : 0.45,
          });
          line.addTo(groups.vessels!);
          if (isPrime) bounds.extend(line.getBounds());
        }

        const last = pts[pts.length - 1];
        leaflet
          .circleMarker(last, {
            radius: isPrime ? 6 : 4,
            color,
            weight: 2,
            fillColor: color,
            fillOpacity: isPrime ? 0.9 : 0.4,
          })
          .bindPopup(
            `<b>${s.vessel_name || "Unnamed vessel"}</b><br/>MMSI ${s.mmsi}<br/>` +
              `${s.vessel_type || "Type unknown"}<br/>` +
              `Posterior ${((s.posterior ?? 0) * 100).toFixed(1)}% · ${s.verdict}<br/>` +
              `CPA ${s.cpa_km?.toFixed(2) ?? "—"} km`,
          )
          .addTo(groups.vessels!);
      });

      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 11 });
      } else {
        map.setView([19, 72], 7);
      }
      setReady(true);
    })();

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [dossier]);

  // Toggle layers without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    (Object.keys(visible) as LayerKey[]).forEach((k) => {
      const g = groupsRef.current[k];
      if (!g) return;
      if (visible[k]) {
        if (!map.hasLayer(g)) g.addTo(map);
      } else if (map.hasLayer(g)) {
        map.removeLayer(g);
      }
    });
  }, [visible, ready]);

  const georefMissing = !dossier.run.is_georeferenced;

  return (
    <div className="panel relative overflow-hidden">
      <div ref={containerRef} style={{ height }} className="w-full" />

      {georefMissing && (
        <div className="absolute inset-0 z-[500] flex items-center justify-center bg-bg/85 p-6 text-center">
          <div className="max-w-md">
            <div className="label mb-2 text-accent">Layer 3 · Georeference gate</div>
            <p className="text-sm leading-relaxed text-fg-muted">
              This scene has no geospatial anchor, so there is nothing to place on a map.
              The detection mask was produced, but drift and attribution were withheld
              rather than invent coordinates.
            </p>
          </div>
        </div>
      )}

      <div className="absolute right-3 top-3 z-[400] panel-sunken p-2 shadow-lg">
        <div className="mb-1.5 flex items-center gap-1.5 px-0.5">
          <Layers size={11} className="text-fg-dim" />
          <span className="label">Layers</span>
        </div>
        <div className="space-y-0.5">
          {(Object.keys(LAYER_LABELS) as LayerKey[]).map((k) => (
            <label
              key={k}
              className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[11px] text-fg-muted transition-colors hover:bg-bg-raised hover:text-fg"
            >
              <input
                type="checkbox"
                checked={visible[k]}
                onChange={() => setVisible((v) => ({ ...v, [k]: !v[k] }))}
                className="h-3 w-3 accent-[var(--color-accent)]"
              />
              <span
                className={cn("h-1.5 w-4 rounded-full")}
                style={{
                  background:
                    k === "hindcast"
                      ? COLORS.hindcast
                      : k === "forecast"
                        ? COLORS.forecast
                        : k === "vessels"
                          ? COLORS.suspect
                          : COLORS.slick,
                }}
              />
              {LAYER_LABELS[k]}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
