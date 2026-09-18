"use client";

import { motion } from "framer-motion";
import { ShieldAlert, ShieldCheck, ShieldQuestion, Ship } from "lucide-react";
import type { Dossier } from "@/types/api";
import { Badge, Meter } from "@/components/ui/primitives";
import { cn, pct } from "@/lib/utils";

/**
 * The headline conclusion. Deliberately the first and largest thing on the page,
 * and deliberately capable of saying "we do not know": an attribution tool that
 * can only ever name a suspect is a tool that will eventually name the wrong one.
 */
export function VerdictBanner({ dossier }: { dossier: Dossier }) {
  const conclusion = dossier.attribution.summary?.conclusion ?? "insufficient_evidence";
  const headline = dossier.attribution.summary?.headline ?? "";
  const unknown = dossier.attribution.unknown_vessel_posterior;
  const top = dossier.suspects[0];
  const stale = dossier.attribution.stale === true;

  const insufficient = conclusion === "insufficient_evidence" || conclusion === "insufficient";
  const strong = conclusion === "strong";
  const probable = conclusion === "probable";

  const Icon = insufficient ? ShieldQuestion : strong ? ShieldAlert : ShieldCheck;
  const tone = insufficient ? "neutral" : strong ? "danger" : "accent";

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "panel relative overflow-hidden p-5 sm:p-6",
        strong && "border-danger/40",
        probable && "border-accent/40",
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          background: `radial-gradient(60% 120% at 12% 0%, ${
            insufficient ? "#7a8699" : strong ? "#e2603f" : "#e8a838"
          }, transparent 70%)`,
        }}
      />

      {stale && (
        <div className="relative mb-4 rounded border border-accent/40 bg-accent/[0.07] p-3">
          <div className="label mb-1 text-accent">Supporting records unavailable</div>
          <p className="text-[12px] leading-snug text-fg-muted">
            {dossier.attribution.stale_reason}
          </p>
        </div>
      )}

      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <Icon
              size={16}
              className={cn(
                insufficient ? "text-fg-dim" : strong ? "text-danger" : "text-accent",
              )}
            />
            <span className="label">Attribution finding</span>
            <Badge tone={tone as any}>{conclusion.replace(/_/g, " ")}</Badge>
          </div>

          <h1 className="font-[family-name:var(--font-display)] text-[22px] font-semibold leading-tight tracking-tight sm:text-[26px]">
            {insufficient
              ? "No vessel can be placed at the release point"
              : stale
                ? "Finding recorded, supporting records since removed"
                : `${top?.vessel_name || "Unnamed vessel"} is the most probable source`}
          </h1>

          {headline && (
            <p className="mt-2.5 max-w-3xl text-[13px] leading-relaxed text-fg-muted">
              {headline}
            </p>
          )}
        </div>

        <div className="w-full shrink-0 space-y-3 lg:w-[300px]">
          {!insufficient && top && !stale && (
            <div className="panel-sunken p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <Ship size={12} className="shrink-0 text-danger" />
                  <span className="truncate text-[13px] font-medium">{top.vessel_name}</span>
                </div>
                <span className="font-[family-name:var(--font-mono)] text-base font-bold text-danger">
                  {pct(top.posterior)}
                </span>
              </div>
              <Meter value={top.posterior ?? 0} tone="danger" />
              <div className="mt-1.5 font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
                MMSI {top.mmsi}
              </div>
            </div>
          )}

          <div className="panel-sunken p-3">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="text-[12px] text-fg-muted">Source not in this AIS data</span>
              <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-fg">
                {pct(unknown)}
              </span>
            </div>
            <Meter value={unknown ?? 0} tone="neutral" />
            <p className="mt-2 text-[11px] leading-snug text-fg-dim">
              Held explicitly as a hypothesis, covering dark vessels, gaps in receiver
              coverage and spoofed identities.
            </p>
          </div>
        </div>
      </div>
    </motion.section>
  );
}
