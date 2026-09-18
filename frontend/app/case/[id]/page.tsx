import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Clock, Cpu, Layers3 } from "lucide-react";
import { Nav } from "@/components/ui/Nav";
import { NoiseOverlay, Badge, Field, SectionHeading } from "@/components/ui/primitives";
import { VerdictBanner } from "@/components/case/VerdictBanner";
import { LookAlikeEvidence } from "@/components/case/LookAlikeEvidence";
import { DriftPanel } from "@/components/case/DriftPanel";
import { SuspectTable } from "@/components/case/SuspectTable";
import { ChainOfCustody } from "@/components/case/ChainOfCustody";
import { RobustnessPanel } from "@/components/case/RobustnessPanel";
import { CaseMap } from "@/components/case/CaseMap";
import { getDossier } from "@/services/api";
import { formatDuration, formatUTC, num } from "@/lib/utils";

export const dynamic = "force-dynamic";

const STAGE_LABELS: Record<string, string> = {
  detection: "Detection",
  lookalike: "Screening",
  drift: "Drift ensemble",
  ais_attribution: "Attribution",
  robustness: "Self-audit",
};

export default async function CasePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let dossier;
  try {
    dossier = await getDossier(id);
  } catch (e) {
    // A 404 is a missing case; anything else is an infrastructure problem and
    // should say so rather than masquerading as "no such case".
    const status = (e as { status?: number })?.status;
    if (status && status !== 404) {
      return (
        <>
          <NoiseOverlay />
          <Nav />
          <main className="mx-auto flex w-full max-w-[1180px] flex-1 flex-col items-center justify-center gap-3 px-6 py-32 text-center">
            <div className="label text-danger">Backend unreachable</div>
            <h1 className="font-[family-name:var(--font-display)] text-2xl font-semibold tracking-tight">
              Could not load this case
            </h1>
            <p className="max-w-md text-[13px] leading-relaxed text-fg-muted">
              {(e as Error).message}
            </p>
            <p className="max-w-md text-[12px] text-fg-dim">
              Check that the Django server is running on port 8000.
            </p>
          </main>
        </>
      );
    }
    notFound();
  }

  const { run, model } = dossier;
  const region = dossier.regions[0];
  const drift = region?.drift ?? null;
  const failed = run.status === "failed";
  const gated = run.stage === "georeference_gated";

  return (
    <>
      <NoiseOverlay />
      <Nav />

      <main className="mx-auto w-full max-w-[1180px] flex-1 space-y-10 px-4 pb-20 pt-6 sm:px-6">
        {/* ── Case header ── */}
        <div>
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.12em] text-fg-dim transition-colors hover:text-accent"
          >
            <ArrowLeft size={10} /> Console
          </Link>

          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="label">Case file</div>
              <h1 className="mt-1 font-[family-name:var(--font-mono)] text-lg text-fg">
                {run.id}
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={failed ? "danger" : gated ? "neutral" : "success"}>
                {run.status}
              </Badge>
              {!run.is_georeferenced && <Badge tone="neutral">no georeference</Badge>}
              {run.regions_rejected_as_lookalike > 0 && (
                <Badge tone="ocean">
                  {run.regions_rejected_as_lookalike} rejected as look-alike
                </Badge>
              )}
              {model.is_fallback && <Badge tone="accent">fallback model</Badge>}
            </div>
          </div>

          {failed && run.error_message && (
            <div className="panel mt-4 border-danger/40 p-4">
              <div className="label mb-1.5 text-danger">Run failed</div>
              <p className="text-[12px] leading-relaxed text-fg-muted">
                {run.error_message}
              </p>
            </div>
          )}

          {gated && run.error_message && (
            <div className="panel mt-4 border-accent/35 p-4">
              <div className="label mb-1.5 text-accent">Layer 3 · georeference gate</div>
              <p className="text-[12px] leading-relaxed text-fg-muted">
                {run.error_message}
              </p>
            </div>
          )}
        </div>

        {!failed && !gated && <VerdictBanner dossier={dossier} />}

        {/* ── Map ── */}
        {region && (
          <section>
            <SectionHeading
              index="01"
              title="The scene"
              hint="Detected slick, reconstructed drift path, the release-point ensemble and every candidate vessel's track."
            />
            <CaseMap dossier={dossier} />
          </section>
        )}

        {region && <LookAlikeEvidence region={region} />}
        {drift && <DriftPanel drift={drift} />}
        {!failed && !gated && <SuspectTable suspects={dossier.suspects} />}
        {!failed && !gated && <RobustnessPanel robustness={dossier.robustness} />}

        {/* ── Run telemetry ── */}
        <section>
          <SectionHeading index="06" title="Run telemetry" />
          <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
            <div className="panel p-4">
              <div className="mb-3 flex items-center gap-1.5">
                <Clock size={12} className="text-accent-2" />
                <span className="label">Stage timings</span>
              </div>
              <div className="space-y-2">
                {Object.entries(run.stage_durations_ms ?? {}).map(([k, v]) => {
                  const total = run.total_duration_ms || 1;
                  return (
                    <div key={k} className="flex items-center gap-3">
                      <span className="w-[108px] shrink-0 text-[11px] text-fg-muted">
                        {STAGE_LABELS[k] ?? k}
                      </span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-bg-sunken">
                        <div
                          className="h-full rounded-full bg-accent-2/60"
                          style={{ width: `${Math.max(2, (v / total) * 100)}%` }}
                        />
                      </div>
                      <span className="w-[62px] shrink-0 text-right font-[family-name:var(--font-mono)] text-[11px] tabular-nums text-fg-muted">
                        {formatDuration(v)}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 flex items-baseline justify-between border-t border-border pt-2.5">
                <span className="text-[12px] text-fg-muted">End to end</span>
                <span className="font-[family-name:var(--font-mono)] text-[14px] font-bold text-accent">
                  {formatDuration(run.total_duration_ms)}
                </span>
              </div>
            </div>

            <div className="panel p-4">
              <div className="mb-2.5 flex items-center gap-1.5">
                <Cpu size={12} className="text-accent" />
                <span className="label">Model</span>
                {model.ensemble_size > 1 && (
                  <Badge tone="ocean">{model.ensemble_size}-model ensemble</Badge>
                )}
              </div>

              {model.ensemble_size > 1 && (
                <div className="mb-3 space-y-1 border-b border-border pb-3">
                  {model.ensemble_members.map((m) => (
                    <div
                      key={m}
                      className="flex items-center gap-1.5 text-[11px] text-fg-muted"
                    >
                      <span className="h-1 w-1 rounded-full bg-accent-2" />
                      {m}
                    </div>
                  ))}
                  <p className="pt-1 text-[10px] leading-snug text-fg-dim">
                    Posteriors averaged. The two architectures fail in different
                    places, so the mean inherits whichever was right rather than
                    splitting the difference.
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <Field label="Primary" value={model.name} mono={false} />
                <Field label="Checkpoint" value={model.checkpoint_id} />
                <Field label="Dice" value={num(model.dice_score, 4)} />
                <Field label="IoU" value={num(model.iou_score, 4)} />
                <Field label="Head" value={model.output_activation || "—"} />
                <Field label="Opened" value={formatUTC(run.created_at)} />
              </div>
            </div>
          </div>
        </section>

        {/* ── Imagery ── */}
        {dossier.imagery && (
          <section>
            <SectionHeading
              index="07"
              title="Imagery"
              hint="The scene as analysed, the continuous posterior, and the thresholded mask. The posterior is kept because a binary mask discards exactly what an operator needs to triage a marginal detection."
            />
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["Input scene", dossier.imagery.uploaded_image],
                ["Posterior", dossier.imagery.probability_map],
                ["Mask", dossier.imagery.result_mask],
              ].map(([label, src]) => (
                <div key={label as string} className="panel overflow-hidden">
                  <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
                    <Layers3 size={11} className="text-fg-dim" />
                    <span className="label">{label}</span>
                  </div>
                  {src ? (
                    // Served by Django from MEDIA_ROOT at arbitrary SAR dimensions.
                    // next/image would proxy and re-encode them, which is the wrong
                    // trade for evidentiary imagery that must stay pixel-exact.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={src as string}
                      alt={label as string}
                      className="aspect-[4/3] w-full bg-bg-sunken object-contain"
                    />
                  ) : (
                    <div className="grid aspect-[4/3] w-full place-items-center bg-bg-sunken text-[11px] text-fg-dim">
                      unavailable
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        <ChainOfCustody dossier={dossier} />
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-[1180px] px-4 py-5 sm:px-6">
          <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.12em] text-fg-dim">
            Indicative analysis for investigative triage. Not a substitute for a
            formal enforcement determination.
          </p>
        </div>
      </footer>
    </>
  );
}
