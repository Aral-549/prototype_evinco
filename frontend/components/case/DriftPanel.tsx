"use client";

import { Wind, Waves, AlertTriangle, Target } from "lucide-react";
import type { DriftBlock } from "@/types/api";
import { Badge, Field, SectionHeading } from "@/components/ui/primitives";
import { coord, formatUTC, num, pct } from "@/lib/utils";

function compass(deg: number): string {
  const points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return points[Math.round(deg / 22.5) % 16];
}

/** Arrow pointing the way the vector acts, with the bearing printed beside it. */
function VectorDial({
  deg,
  label,
  value,
  hint,
  icon: Icon,
}: {
  deg: number;
  label: string;
  value: string;
  hint: string;
  icon: any;
}) {
  return (
    <div className="panel-sunken flex items-center gap-3 p-3">
      <div className="relative grid h-11 w-11 shrink-0 place-items-center rounded-full border border-border-bright">
        <div
          className="absolute h-[18px] w-[2px] origin-bottom rounded-full bg-accent-2"
          style={{ transform: `rotate(${deg}deg) translateY(-4px)` }}
        />
        <Icon size={11} className="text-fg-dim" />
      </div>
      <div className="min-w-0">
        <div className="label">{label}</div>
        <div className="mt-0.5 font-[family-name:var(--font-mono)] text-[13px]">{value}</div>
        <div className="text-[10px] text-fg-dim">
          {compass(deg)} · {deg.toFixed(0)}° {hint}
        </div>
      </div>
    </div>
  );
}

export function DriftPanel({ drift }: { drift: DriftBlock }) {
  return (
    <div>
      <SectionHeading
        index="03"
        title="Where did it come from?"
        hint="A stochastic ensemble advected backward through a time-varying met-ocean field. The uncertainty below is measured from the ensemble's own spread, not asserted by a formula."
        action={
          <Badge tone="ocean">
            {drift.n_particles} particles · seed {drift.ensemble_seed}
          </Badge>
        }
      />

      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-1.5">
            <Target size={12} className="text-accent" />
            <span className="label">Reconstructed release</span>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            <Field label="Latitude" value={coord(drift.origin_lat, "lat")} />
            <Field label="Longitude" value={coord(drift.origin_lon, "lon")} />
            <Field label="Release time" value={formatUTC(drift.origin_time)} />
            <Field label="Drifted for" value={num(drift.duration_hours, 0, " h")} />
          </div>

          <div className="mt-4 border-t border-border pt-3">
            <div className="label mb-2.5">Confidence radii</div>
            <div className="space-y-2.5">
              {[
                { p: "50%", v: drift.radius_50_km, w: 0.55 },
                { p: "90%", v: drift.radius_90_km, w: 1.0 },
              ].map((r) => (
                <div key={r.p} className="flex items-center gap-3">
                  <span className="w-9 font-[family-name:var(--font-mono)] text-[11px] text-fg-dim">
                    {r.p}
                  </span>
                  <div className="relative h-4 flex-1 overflow-hidden rounded bg-bg-sunken">
                    <div
                      className="h-full rounded bg-accent/30"
                      style={{ width: `${r.w * 100}%` }}
                    />
                  </div>
                  <span className="w-[74px] text-right font-[family-name:var(--font-mono)] text-[12px] tabular-nums">
                    {num(r.v, 1, " km")}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-2.5 text-[11px] leading-snug text-fg-dim">
              Half the release hypotheses fall within {num(drift.radius_50_km, 1)} km of the
              point above; nine in ten fall within {num(drift.radius_90_km, 1)} km.
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <VectorDial
            deg={drift.wind_direction_deg}
            label="Wind at the scene"
            value={`${num(drift.wind_speed_mps, 1)} m/s`}
            hint="from"
            icon={Wind}
          />
          <VectorDial
            deg={drift.current_direction_deg}
            label="Surface current"
            value={`${num(drift.current_speed_mps, 2)} m/s`}
            hint="toward"
            icon={Waves}
          />

          <div className="panel p-3">
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Evaporated"
                value={pct(drift.evaporated_fraction)}
                title="First-order weathering estimate over the hindcast window."
              />
              <Field label="Met-ocean" value={drift.metocean_source} />
            </div>
            {drift.metocean_degraded_steps > 0 && (
              <p className="mt-2.5 border-t border-border pt-2 text-[11px] text-fg-dim">
                {drift.metocean_degraded_steps} integration step
                {drift.metocean_degraded_steps === 1 ? "" : "s"} fell back to the previous
                field after a met-ocean fetch failed.
              </p>
            )}
          </div>

          {drift.weathering_warning && (
            <div className="panel border-accent/35 p-3">
              <div className="mb-1.5 flex items-center gap-1.5">
                <AlertTriangle size={12} className="text-accent" />
                <span className="label text-accent">Weathering caveat</span>
              </div>
              <p className="text-[11px] leading-snug text-fg-muted">
                {drift.weathering_warning}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
