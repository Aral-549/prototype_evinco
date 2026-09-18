"use client";

import { motion } from "framer-motion";
import { Activity, AlertTriangle, CheckCircle2, ShieldQuestion } from "lucide-react";
import type { Robustness } from "@/types/api";
import { Badge, Meter, SectionHeading, Field } from "@/components/ui/primitives";
import { cn, pct } from "@/lib/utils";

const ASSESSMENT = {
  robust: {
    tone: "success" as const,
    icon: CheckCircle2,
    headline: "The finding survives its own audit",
    blurb:
      "It does not rest on any single assumption: it holds across the full span of defensible drift durations, windage factors and met-ocean error.",
  },
  conditional: {
    tone: "accent" as const,
    icon: ShieldQuestion,
    headline: "The finding holds, but not everywhere",
    blurb:
      "It survives most of the assumption space. The breaking points below sit inside what an expert would accept, so they should be resolved before it is relied on.",
  },
  fragile: {
    tone: "danger" as const,
    icon: AlertTriangle,
    headline: "The finding is contingent",
    blurb:
      "It does not survive ordinary variation in assumptions nobody independently measured. Treat it as a lead for investigation, not as an attribution.",
  },
};

const PARAM_LABELS: Record<string, string> = {
  duration_scale: "Time adrift",
  windage_mean: "Wind drift factor",
  deflection_deg: "Ekman deflection",
  wind_scale: "Wind speed error",
  current_scale: "Current speed error",
  capture_scale: "Positional tolerance",
};

/**
 * The adversarial self-audit.
 *
 * A posterior on its own is conditional on a stack of assumptions nobody measured:
 * that the slick drifted for 24 hours, that windage is 3%, that the met-ocean model
 * was right. This panel reports what happens when those are varied across the
 * ranges a domain expert would accept — so a conclusion that holds only at exactly
 * the assumed drift duration is never presented in the same voice as one that holds
 * everywhere.
 */
export function RobustnessPanel({ robustness }: { robustness: Robustness }) {
  if (!robustness || robustness.error || !robustness.scenarios_run) {
    return null;
  }

  const assessment = robustness.assessment ?? "fragile";
  const meta = ASSESSMENT[assessment] ?? ASSESSMENT.fragile;
  const Icon = meta.icon;
  const stability = robustness.stability ?? 0;

  return (
    <div>
      <SectionHeading
        index="05"
        title="We tried to break this conclusion"
        hint={`The attribution was re-run against ${robustness.scenarios_run} alternative assumption sets, each drawn from ranges a domain expert would accept.`}
        action={<Badge tone={meta.tone}>{assessment}</Badge>}
      />

      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div
          className={cn(
            "panel p-5",
            assessment === "fragile" && "border-danger/40",
            assessment === "robust" && "border-success/35",
          )}
        >
          <div className="flex items-start gap-3">
            <Icon
              size={17}
              className={cn(
                "mt-0.5 shrink-0",
                assessment === "robust"
                  ? "text-success"
                  : assessment === "fragile"
                    ? "text-danger"
                    : "text-accent",
              )}
            />
            <div className="min-w-0">
              <h3 className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-tight">
                {meta.headline}
              </h3>
              <p className="mt-1.5 text-[12px] leading-relaxed text-fg-muted">
                {meta.blurb}
              </p>
            </div>
          </div>

          <div className="mt-4 border-t border-border pt-4">
            <div className="mb-1.5 flex items-baseline justify-between">
              <span className="label">Conclusion held in</span>
              <span
                className={cn(
                  "font-[family-name:var(--font-mono)] text-xl font-bold",
                  assessment === "robust"
                    ? "text-success"
                    : assessment === "fragile"
                      ? "text-danger"
                      : "text-accent",
                )}
              >
                {pct(stability)}
              </span>
            </div>
            <Meter value={stability} tone={meta.tone} />
            <div className="mt-1.5 flex justify-between font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
              <span>of {robustness.scenarios_run} assumption sets</span>
              <span>
                posterior {pct(robustness.posterior_min)}–{pct(robustness.posterior_max)}
              </span>
            </div>
          </div>

          {robustness.narrative && robustness.narrative.length > 0 && (
            <ul className="mt-4 space-y-2 border-t border-border pt-3">
              {robustness.narrative.map((line, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-fg-muted">
                  <span className="mr-1.5 text-accent">·</span>
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          {robustness.most_influential && (
            <div className="panel p-4">
              <div className="mb-2 flex items-center gap-1.5">
                <Activity size={12} className="text-accent" />
                <span className="label">Decided by</span>
              </div>
              <div className="font-[family-name:var(--font-display)] text-[15px] font-semibold">
                {PARAM_LABELS[robustness.most_influential] ??
                  robustness.most_influential.replace(/_/g, " ")}
              </div>
              <p className="mt-2 text-[11px] leading-snug text-fg-dim">
                Pin this down first. An independent estimate of it would do more to
                settle this case than any additional AIS data.
              </p>
            </div>
          )}

          <div className="panel p-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Scenarios" value={String(robustness.scenarios_run)} />
              <Field label="Median posterior" value={pct(robustness.posterior_median)} />
              <Field label="Verdict held" value={pct(robustness.verdict_stability)} />
              <Field
                label="Subject"
                value={robustness.baseline_mmsi || "no vessel named"}
              />
            </div>
          </div>
        </div>
      </div>

      {robustness.breaking_points && robustness.breaking_points.length > 0 && (
        <div className="panel mt-3 p-4">
          <div className="mb-3 flex items-center gap-1.5">
            <AlertTriangle size={12} className="text-danger" />
            <span className="label text-danger">Breaking points</span>
            <span className="text-[11px] text-fg-dim">
              — the smallest defensible changes that flip the leading candidate
            </span>
          </div>
          <div className="space-y-2">
            {robustness.breaking_points.map((bp, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06, duration: 0.35 }}
                className="panel-sunken flex items-start gap-3 p-3"
              >
                <span className="shrink-0 rounded border border-danger/40 bg-danger/10 px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] text-danger">
                  {bp.value}
                </span>
                <div className="min-w-0">
                  <p className="text-[12px] leading-snug text-fg-muted">{bp.note}</p>
                  <p className="mt-1 font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
                    → leading candidate becomes {bp.new_top}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
