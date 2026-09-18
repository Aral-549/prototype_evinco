import Link from "next/link";
import { Radar } from "lucide-react";

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="group flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded border border-accent/40 bg-accent/10">
            <Radar size={14} className="text-accent" />
          </div>
          <div className="leading-none">
            <div className="font-[family-name:var(--font-display)] text-[15px] font-semibold tracking-tight">
              MarSlick
            </div>
            <div className="mt-0.5 font-[family-name:var(--font-mono)] text-[9px] uppercase tracking-[0.14em] text-fg-dim">
              SIH 26143
            </div>
          </div>
        </Link>

        <nav className="flex items-center gap-4 font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-[0.1em] text-fg-dim">
          <Link href="/" className="transition-colors hover:text-fg">
            Console
          </Link>
          <a
            href="/api/docs/"
            className="transition-colors hover:text-fg"
            target="_blank"
            rel="noreferrer"
          >
            API
          </a>
        </nav>
      </div>
    </header>
  );
}
