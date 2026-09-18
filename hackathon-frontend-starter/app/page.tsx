import { Navbar } from "@/components/navbar";
import { Hero } from "@/components/hero";
import { NoiseOverlay } from "@/components/ui/noise-overlay";
import { SpotlightCard } from "@/components/ui/spotlight-card";
import { BentoGrid, BentoItem } from "@/components/ui/bento-grid";
import { Marquee } from "@/components/ui/marquee";
import { FadeIn } from "@/components/ui/text-reveal";

const stack = ["Next.js", "Tailwind v4", "Framer Motion", "TypeScript", "Vercel", "Your API here"];

export default function Home() {
  return (
    <>
      <NoiseOverlay />
      <Navbar />
      <main className="flex-1">
        <Hero />

        <section className="border-y border-border/60 py-6">
          <Marquee>
            {stack.map((item) => (
              <span
                key={item}
                className="font-mono text-sm uppercase tracking-widest text-fg-muted"
              >
                {item}
              </span>
            ))}
          </Marquee>
        </section>

        <section id="work" className="mx-auto max-w-6xl px-6 py-24">
          <FadeIn>
            <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent">
              What it does
            </span>
            <h2 className="mt-3 max-w-xl font-display text-3xl font-medium tracking-tight sm:text-4xl">
              An uneven grid, on purpose — not three identical cards.
            </h2>
          </FadeIn>

          <BentoGrid className="mt-10">
            <BentoItem span="sm:col-span-4">
              <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
                Feature one
              </p>
              <p className="mt-3 text-xl">
                Give the biggest cell to the thing judges should remember —
                a screenshot, a chart, a live demo embed.
              </p>
            </BentoItem>
            <BentoItem span="sm:col-span-2">
              <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
                Feature two
              </p>
              <p className="mt-3 text-xl">Smaller supporting claim here.</p>
            </BentoItem>
            <BentoItem span="sm:col-span-2">
              <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
                Feature three
              </p>
              <p className="mt-3 text-xl">Another supporting claim here.</p>
            </BentoItem>
            <BentoItem span="sm:col-span-4">
              <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
                Feature four
              </p>
              <p className="mt-3 text-xl">
                Uneven spans keep the eye moving instead of settling into a
                predictable triptych.
              </p>
            </BentoItem>
          </BentoGrid>
        </section>

        <section id="team" className="mx-auto max-w-6xl px-6 py-24">
          <FadeIn>
            <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent">
              Try the interaction
            </span>
            <h2 className="mt-3 max-w-xl font-display text-3xl font-medium tracking-tight sm:text-4xl">
              A card that responds to the cursor, used once — not everywhere.
            </h2>
          </FadeIn>

          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {["Move your mouse", "over these panels", "to see the spotlight"].map((label) => (
              <SpotlightCard key={label}>
                <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
                  Hover me
                </p>
                <p className="mt-3 text-lg">{label}</p>
              </SpotlightCard>
            ))}
          </div>
        </section>

        <section id="demo" className="mx-auto max-w-6xl px-6 py-24">
          <div className="panel flex flex-col items-start gap-4 p-10 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-display text-2xl font-medium tracking-tight sm:text-3xl">
                Ready to plug in your real content?
              </h2>
              <p className="mt-2 text-fg-muted">
                Swap the tokens in <code className="font-mono text-accent">app/globals.css</code>{" "}
                for a different palette and font pair, and this whole site
                becomes a new &ldquo;look&rdquo; in minutes.
              </p>
            </div>
            <a
              href="#"
              className="shrink-0 rounded-[6px] bg-accent px-5 py-3 text-sm font-semibold text-bg transition-opacity hover:opacity-90"
            >
              Deploy this
            </a>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/60 px-6 py-10 text-center text-sm text-fg-muted">
        Built with the hackathon-frontend-design skill · replace this footer
      </footer>
    </>
  );
}
