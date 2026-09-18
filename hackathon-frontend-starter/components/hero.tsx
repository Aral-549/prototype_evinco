import { TextReveal, FadeIn } from "@/components/ui/text-reveal";

/**
 * Deliberately NOT a centered headline + subhead + single button. Off-center,
 * asymmetric grid with the copy anchored left and a supporting panel right —
 * that alone reads as "someone made a decision here" instead of a template.
 */
export function Hero() {
  return (
    <section className="mx-auto grid max-w-6xl gap-10 px-6 py-20 sm:grid-cols-5 sm:py-32">
      <div className="sm:col-span-3">
        <FadeIn>
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent">
            Built in a weekend
          </span>
        </FadeIn>
        <TextReveal
          text="Say what your product actually does, here."
          className="mt-4 font-display text-4xl font-medium leading-[1.05] tracking-tight sm:text-6xl"
        />
        <FadeIn delay={0.4} className="mt-6 max-w-md text-lg text-fg-muted">
          Replace this with a specific claim only your project can make — not
          &quot;build faster, ship smarter.&quot; Name the user, the problem, and the
          number that proves it works.
        </FadeIn>
        <FadeIn delay={0.5} className="mt-8 flex flex-wrap gap-3">
          <a
            href="#demo"
            className="rounded-[6px] bg-accent px-5 py-3 text-sm font-semibold text-bg transition-opacity hover:opacity-90"
          >
            See the demo
          </a>
          <a
            href="#team"
            className="panel px-5 py-3 text-sm font-semibold transition-colors hover:border-accent"
          >
            Read the writeup
          </a>
        </FadeIn>
      </div>

      <FadeIn delay={0.3} className="sm:col-span-2">
        <div className="panel h-full min-h-[280px] p-6">
          <p className="font-mono text-xs uppercase tracking-widest text-fg-muted">
            Live metric
          </p>
          <p className="mt-3 font-display text-5xl font-semibold text-accent">
            2.4×
          </p>
          <p className="mt-2 text-sm text-fg-muted">
            faster than the baseline you&apos;re comparing against — put the
            real number here once you have it.
          </p>
        </div>
      </FadeIn>
    </section>
  );
}
