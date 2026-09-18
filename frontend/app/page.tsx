import Link from "next/link";
import { ArrowRight, Clock, Crosshair, Waves } from "lucide-react";
import { Nav } from "@/components/ui/Nav";
import { NoiseOverlay, TextReveal, FadeIn, SpotlightCard, SectionHeading } from "@/components/ui/primitives";
import { UploadConsole } from "@/components/upload/UploadConsole";
import { RecentCases } from "@/components/ui/RecentCases";
import { getRecentRuns } from "@/services/api";

export const dynamic = "force-dynamic";

const PIPELINE = [
  {
    icon: Crosshair,
    title: "Detect, then interrogate",
    body: "A U-Net segments dark regions in Sentinel-1 backscatter. Because a dark patch is not automatically oil, every candidate is then tested against the physics that separate a slick from a calm zone, a biogenic film or a rain cell.",
  },
  {
    icon: Waves,
    title: "Rewind the ocean",
    body: "Five hundred particles are advected backward through an hourly met-ocean field, each drawing its own wind, current, windage and drift duration. The result is a probability distribution over the release point, not a single dot.",
  },
  {
    icon: Clock,
    title: "Ask who was there",
    body: "Each candidate vessel's AIS track is interpolated to every ensemble member's release time. The share of hypotheses that place it at the scene becomes its likelihood — joint in space and time, so being near at the wrong moment counts for nothing.",
  },
];

export default async function HomePage() {
  let runs: Awaited<ReturnType<typeof getRecentRuns>> = [];
  try {
    runs = await getRecentRuns(6);
  } catch {
    // The console must still render when the backend is down; the upload path
    // surfaces the connection error where the operator will actually see it.
  }

  return (
    <>
      <NoiseOverlay />
      <Nav />

      <main className="mx-auto w-full max-w-[1180px] flex-1 px-4 pb-20 sm:px-6">
        {/* ── Hero: asymmetric, copy left, numbers right ── */}
        <section className="relative">
          <div aria-hidden className="grid-bg pointer-events-none absolute inset-x-0 -top-4 h-[300px]" />

          <div className="relative grid gap-8 pb-10 pt-14 lg:grid-cols-[1.35fr_1fr] lg:items-end">
            <div>
              <FadeIn>
                <div className="mb-4 inline-flex items-center gap-2 rounded border border-border bg-bg-raised px-2.5 py-1">
                  <span className="relative grid h-1.5 w-1.5 place-items-center">
                    <span className="pulse-ring absolute inset-0 rounded-full" />
                    <span className="relative h-1.5 w-1.5 rounded-full bg-accent" />
                  </span>
                  <span className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.12em] text-fg-muted">
                    Smart India Hackathon 2026 · PS 26143
                  </span>
                </div>
              </FadeIn>

              <TextReveal
                text="Find the ship that spilled it."
                className="font-[family-name:var(--font-display)] text-[38px] font-semibold leading-[1.05] tracking-[-0.02em] sm:text-[52px]"
              />

              <FadeIn delay={0.25}>
                <p className="mt-4 max-w-[52ch] text-[14px] leading-relaxed text-fg-muted">
                  A tanker washes its tanks at night. By the time a satellite passes, the
                  slick has drifted tens of nautical miles and a thousand ships have
                  crossed the area. Coastal authorities take two to three days to work
                  backward by hand, and the vessel is in foreign waters by then.
                </p>
                <p className="mt-3 max-w-[52ch] text-[14px] leading-relaxed text-fg-muted">
                  MarSlick does that reconstruction in seconds — and is built to say
                  <span className="text-fg"> &ldquo;insufficient evidence&rdquo;</span> when
                  the data does not support naming anyone.
                </p>
              </FadeIn>
            </div>

            <FadeIn delay={0.35}>
              <div className="panel divide-y divide-[var(--color-border)]">
                {[
                  ["48–72 h", "Manual attribution today"],
                  ["~10 s", "End-to-end, this pipeline"],
                  ["500", "Drift hypotheses per case"],
                  ["SHA-256", "Sealed, reproducible record"],
                ].map(([v, l]) => (
                  <div key={l} className="flex items-baseline justify-between gap-4 px-4 py-3">
                    <span className="font-[family-name:var(--font-mono)] text-[17px] font-bold text-accent">
                      {v}
                    </span>
                    <span className="text-right text-[11px] leading-tight text-fg-muted">
                      {l}
                    </span>
                  </div>
                ))}
              </div>
            </FadeIn>
          </div>
        </section>

        {/* ── Console ── */}
        <section className="pt-4">
          <SectionHeading
            index="01"
            title="Open a case"
            hint="Upload a SAR scene. Detection runs on the image; drift and attribution require a georeference."
          />
          <UploadConsole />
        </section>

        {/* ── How it works ── */}
        <section className="pt-12">
          <SectionHeading index="02" title="How the attribution is made" />
          <div className="grid gap-3 sm:grid-cols-3">
            {PIPELINE.map((p, i) => (
              <FadeIn key={p.title} delay={i * 0.08}>
                <SpotlightCard className="h-full p-5">
                  <p.icon size={16} className="mb-3 text-accent" />
                  <h3 className="font-[family-name:var(--font-display)] text-[15px] font-semibold tracking-tight">
                    {p.title}
                  </h3>
                  <p className="mt-2 text-[12px] leading-relaxed text-fg-muted">{p.body}</p>
                </SpotlightCard>
              </FadeIn>
            ))}
          </div>
        </section>

        {/* ── Recent cases ── */}
        <section className="pt-12">
          <SectionHeading index="03" title="Recent cases" />
          <RecentCases runs={runs} />
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6">
          <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.12em] text-fg-dim">
            MarSlick · SAR forensic attribution prototype
          </p>
          <Link
            href="/api/docs/"
            className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.12em] text-fg-dim transition-colors hover:text-accent"
          >
            OpenAPI schema <ArrowRight size={10} />
          </Link>
        </div>
      </footer>
    </>
  );
}
