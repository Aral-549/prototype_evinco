"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Radio, TrendingDown, Anchor, Navigation, ShieldAlert } from "lucide-react";
import type { Suspect } from "@/types/api";
import { Badge, Meter, SectionHeading, Field } from "@/components/ui/primitives";
import { cn, num, pct, formatUTC } from "@/lib/utils";

const ANOMALY_META: Record<string, { label: string; icon: any; tone: string }> = {
  dark_vessel_gap: { label: "Dark vessel", icon: Radio, tone: "danger" },
  ais_gap_long: { label: "AIS gap (long)", icon: Radio, tone: "danger" },
  ais_gap_short: { label: "AIS gap", icon: Radio, tone: "accent" },
  speed_drop: { label: "Speed drop", icon: TrendingDown, tone: "accent" },
  loitering: { label: "Loitering", icon: Anchor, tone: "ocean" },
  course_deviation: { label: "Course change", icon: Navigation, tone: "ocean" },
};

const VERDICT_TONE: Record<string, string> = {
  strong: "danger",
  probable: "accent",
  weak: "neutral",
  insufficient: "neutral",
};

/**
 * Ranked by Bayesian posterior, with the legacy weighted score shown alongside.
 * Where the two disagree the disagreement is the point: the old score summed a
 * proximity minimum and a time minimum that need not come from the same AIS
 * report, so it rewarded "near at some point" and "present at some point"
 * independently rather than "there at the right time".
 */
export function SuspectTable({ suspects }: { suspects: Suspect[] }) {
  const [open, setOpen] = useState<string | null>(
    suspects[0]?.posterior ? suspects[0].mmsi : null,
  );

  if (!suspects.length) {
    return (
      <div>
        <SectionHeading index="04" title="Candidate vessels" />
        <div className="panel p-8 text-center text-[13px] text-fg-muted">
          No AIS tracks were available in the window around the reconstructed release.
        </div>
      </div>
    );
  }

  const disagrees =
    suspects.length > 1 &&
    [...suspects].sort(
      (a, b) => b.legacy_composite_score - a.legacy_composite_score,
    )[0]?.mmsi !== suspects[0]?.mmsi;

  return (
    <div>
      <SectionHeading
        index="04"
        title="Candidate vessels"
        hint="Posterior probability that this vessel released the slick, evaluated jointly in space and time against every member of the drift ensemble."
        action={
          disagrees ? (
            <Badge tone="accent" title="The legacy weighted score would have ranked a different vessel first.">
              methods disagree
            </Badge>
          ) : undefined
        }
      />

      <div className="panel divide-y divide-[var(--color-border)] overflow-hidden">
        <div className="hidden grid-cols-[28px_1fr_120px_96px_86px_20px] gap-3 bg-bg-sunken px-4 py-2 sm:grid">
          <div className="label">#</div>
          <div className="label">Vessel</div>
          <div className="label">Posterior</div>
          <div className="label">CPA</div>
          <div className="label">Verdict</div>
          <div />
        </div>

        {suspects.map((s, i) => {
          const isOpen = open === s.mmsi;
          const isPrime = i === 0 && (s.posterior ?? 0) > 0.15;
          return (
            <div key={s.mmsi} className={cn(isPrime && "bg-danger/[0.04]")}>
              <button
                onClick={() => setOpen(isOpen ? null : s.mmsi)}
                aria-expanded={isOpen}
                className="grid w-full grid-cols-[28px_1fr_20px] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-bg-sunken sm:grid-cols-[28px_1fr_120px_96px_86px_20px]"
              >
                <div
                  className={cn(
                    "font-[family-name:var(--font-mono)] text-sm font-bold",
                    isPrime ? "text-danger" : "text-fg-dim",
                  )}
                >
                  {s.rank}
                </div>

                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">
                    {s.vessel_name || "Unnamed vessel"}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
                      {s.mmsi}
                    </span>
                    {s.vessel_type && (
                      <span className="text-[10px] text-fg-dim">{s.vessel_type}</span>
                    )}
                    {!s.integrity_plausible && (
                      <Badge
                        tone="danger"
                        title="This vessel's AIS track is not physically self-consistent. Grounds for review, not proof of spoofing."
                      >
                        <ShieldAlert size={9} />
                        track suspect
                      </Badge>
                    )}
                    {s.anomalies?.map((a) => {
                      const meta = ANOMALY_META[a] ?? {
                        label: a.replace(/_/g, " "),
                        icon: Radio,
                        tone: "neutral",
                      };
                      const Icon = meta.icon;
                      return (
                        <Badge key={a} tone={meta.tone as any}>
                          <Icon size={9} />
                          {meta.label}
                        </Badge>
                      );
                    })}
                  </div>
                </div>

                <div className="hidden sm:block">
                  <div className="mb-1 font-[family-name:var(--font-mono)] text-[13px] font-bold tabular-nums">
                    {pct(s.posterior, 1)}
                  </div>
                  <Meter
                    value={s.posterior ?? 0}
                    tone={isPrime ? "danger" : "neutral"}
                  />
                </div>

                <div className="hidden font-[family-name:var(--font-mono)] text-[12px] tabular-nums text-fg-muted sm:block">
                  {num(s.cpa_km, 2, " km")}
                </div>

                <div className="hidden sm:block">
                  <Badge tone={(VERDICT_TONE[s.verdict] ?? "neutral") as any}>
                    {s.verdict || "—"}
                  </Badge>
                </div>

                <ChevronDown
                  size={14}
                  className={cn(
                    "text-fg-dim transition-transform",
                    isOpen && "rotate-180",
                  )}
                />
              </button>

              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="border-t border-border bg-bg-sunken px-4 py-4">
                      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
                        <div>
                          <div className="label mb-2">Reasoning</div>
                          <ul className="space-y-2">
                            {s.explanation?.map((line, k) => (
                              <li
                                key={k}
                                className="text-[12px] leading-relaxed text-fg-muted"
                              >
                                <span className="mr-1.5 text-accent">·</span>
                                {line}
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="space-y-3">
                          <div className="grid grid-cols-2 gap-3">
                            <Field
                              label="Spatio-temporal"
                              value={num((s.spatiotemporal_likelihood ?? 0) * 100, 2, "%")}
                              title="Share of drift-ensemble members that place this vessel at the release point at that member's release time."
                            />
                            <Field
                              label="Behavioural ×"
                              value={num(s.behavioural_factor, 2)}
                              title="Multiplicative likelihood ratio from anomalies. Multiplying a zero likelihood by any factor still leaves zero."
                            />
                            <Field label="CPA time" value={formatUTC(s.cpa_time)} />
                            <Field label="Flag" value={s.flag || "—"} />
                          </div>

                          {s.integrity_flags?.length > 0 && (
                            <div className="panel border-danger/35 p-3">
                              <div className="label mb-2 text-danger">
                                AIS integrity
                              </div>
                              <ul className="space-y-1.5">
                                {s.integrity_flags.map((f, k) => (
                                  <li
                                    key={k}
                                    className="text-[11px] leading-snug text-fg-muted"
                                  >
                                    <span className="mr-1 text-danger">·</span>
                                    {f.detail}
                                  </li>
                                ))}
                              </ul>
                              <p className="mt-2 border-t border-border pt-2 text-[10px] leading-snug text-fg-dim">
                                AIS is an unauthenticated broadcast. These show the track
                                is physically inconsistent, which is grounds for review —
                                not a determination that it was falsified.
                              </p>
                            </div>
                          )}

                          <div className="panel p-3">
                            <div className="label mb-2">Legacy weighted score</div>
                            <div className="font-[family-name:var(--font-mono)] text-[15px] text-fg-muted tabular-nums">
                              {num(s.legacy_composite_score, 4)}
                            </div>
                            <div className="mt-0.5 font-[family-name:var(--font-mono)] text-[10px] leading-snug text-fg-dim">
                              0.40·prox + 0.35·time + 0.25·behav
                            </div>
                            <p className="mt-2 text-[10px] leading-snug text-fg-dim">
                              Shown for comparison. Its proximity and time terms came from
                              different AIS reports, so a vessel could score highly for
                              being near the origin at entirely the wrong moment.
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
