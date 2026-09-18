"use client";

import { motion } from "framer-motion";
import { Droplets, Info } from "lucide-react";
import type { Region } from "@/types/api";
import { Badge, Field, SectionHeading } from "@/components/ui/primitives";
import { cn, num, pct } from "@/lib/utils";

const FEATURE_LABELS: Record<string, string> = {
  damping_contrast: "Backscatter damping",
  edge_sharpness: "Edge definition",
  interior_homogeneity: "Interior smoothness",
  shape_elongation: "Elongation",
  wind_plausibility: "Wind plausibility",
  model_confidence: "U-Net posterior",
  bias: "Prior",
};

const FEATURE_HELP: Record<string, string> = {
  damping_contrast:
    "How much darker the region is than the sea immediately around it. Mineral oil suppresses capillary waves strongly; this is the single most decisive discriminator.",
  edge_sharpness:
    "Oil has a surface-tension boundary and a steep backscatter step. A low-wind calm zone grades smoothly into the surrounding sea.",
  interior_homogeneity:
    "Oil damps the surface uniformly. Biogenic slicks and rain cells are patchy and streaky inside.",
  shape_elongation:
    "An operational discharge is laid along the vessel's track, giving a long thin slick. Calm zones and rain cells are compact blobs.",
  wind_plausibility:
    "Below about 3 m/s there are no capillary waves for oil to damp, so a dark patch is more likely the calm itself. Above about 12 m/s wind mixing disperses surface oil.",
  model_confidence: "The segmentation model's own posterior over the region.",
  bias: "The baseline prior before any measurement is considered.",
};

/**
 * A diverging log-odds chart: exactly which physical evidence pushed this region
 * toward or away from "mineral oil". The contributions sum to the model's logit,
 * so this is the decision itself rather than a post-hoc narration of it.
 */
export function LookAlikeEvidence({ region }: { region: Region }) {
  const contributions = region.lookalike_contributions ?? {};
  const entries = Object.entries(contributions).sort(
    (a, b) => Math.abs(b[1]) - Math.abs(a[1]),
  );
  const maxAbs = Math.max(0.5, ...entries.map(([, v]) => Math.abs(v)));

  const verdict = region.lookalike_verdict;
  const tone =
    verdict === "probable_oil" ? "accent" : verdict === "ambiguous" ? "neutral" : "ocean";

  return (
    <div>
      <SectionHeading
        index="02"
        title="Is it actually oil?"
        hint="Dark patches in SAR are also produced by calm zones, biogenic slicks and rain cells. Each physical discriminator below is weighed separately."
        action={
          <Badge tone={tone as any}>{(verdict || "unscreened").replace(/_/g, " ")}</Badge>
        }
      />

      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div className="panel p-4">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <span className="label">Evidence, in log-odds</span>
            <div className="flex items-center gap-3 font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
              <span>← look-alike</span>
              <span>oil →</span>
            </div>
          </div>

          <div className="space-y-1.5">
            {entries.map(([key, value], i) => {
              const width = (Math.abs(value) / maxAbs) * 50;
              const positive = value >= 0;
              return (
                <div key={key} className="group flex items-center gap-2.5">
                  <div
                    className="w-[132px] shrink-0 truncate text-right text-[11px] text-fg-muted"
                    title={FEATURE_HELP[key]}
                  >
                    {FEATURE_LABELS[key] ?? key}
                  </div>

                  <div className="relative h-4 flex-1">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-border-bright" />
                    <motion.div
                      className={cn(
                        "absolute inset-y-[3px] rounded-[2px]",
                        positive ? "bg-accent" : "bg-accent-2",
                      )}
                      style={positive ? { left: "50%" } : { right: "50%" }}
                      initial={{ width: 0 }}
                      animate={{ width: `${width}%` }}
                      transition={{
                        duration: 0.55,
                        delay: 0.05 + i * 0.05,
                        ease: [0.22, 1, 0.36, 1],
                      }}
                    />
                  </div>

                  <div
                    className={cn(
                      "w-[54px] shrink-0 font-[family-name:var(--font-mono)] text-[11px] tabular-nums",
                      positive ? "text-accent" : "text-accent-2",
                    )}
                  >
                    {value >= 0 ? "+" : ""}
                    {value.toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex items-baseline justify-between border-t border-border pt-3">
            <span className="text-[12px] text-fg-muted">Probability this is mineral oil</span>
            <span className="font-[family-name:var(--font-mono)] text-xl font-bold text-accent">
              {pct(region.oil_probability, 1)}
            </span>
          </div>
        </div>

        <div className="space-y-3">
          <div className="panel p-4">
            <div className="mb-2.5 flex items-center gap-1.5">
              <Droplets size={12} className="text-accent-2" />
              <span className="label">Extent and volume</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Area" value={num(region.area_sq_km, 1, " km²")} />
              <Field label="Model posterior" value={pct(region.confidence, 1)} />
              <Field
                label="Volume band"
                value={
                  region.volume_estimate?.volume_m3_min !== undefined
                    ? `${num(region.volume_estimate.volume_m3_min, 0)}–${num(
                        region.volume_estimate.volume_m3_max,
                        0,
                      )} m³`
                    : "—"
                }
              />
              <Field label="Shape ratio" value={num(region.shape_complexity, 2)} />
            </div>
            {region.volume_estimate?.caveat && (
              <p className="mt-3 border-t border-border pt-2.5 text-[11px] leading-snug text-fg-dim">
                {region.volume_estimate.caveat}
              </p>
            )}
          </div>

          {region.lookalike_notes?.length > 0 && (
            <div className="panel p-4">
              <div className="mb-2 flex items-center gap-1.5">
                <Info size={12} className="text-fg-dim" />
                <span className="label">Screening notes</span>
              </div>
              <ul className="space-y-2">
                {region.lookalike_notes.map((note, i) => (
                  <li key={i} className="text-[11px] leading-snug text-fg-muted">
                    <span className="mr-1.5 text-accent">·</span>
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
