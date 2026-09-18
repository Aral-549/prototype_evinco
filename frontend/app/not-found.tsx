import Link from "next/link";
import { Nav } from "@/components/ui/Nav";
import { NoiseOverlay } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <>
      <NoiseOverlay />
      <Nav />
      <main className="mx-auto flex w-full max-w-[1180px] flex-1 flex-col items-center justify-center gap-4 px-6 py-32 text-center">
        <div className="label">404</div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-semibold tracking-tight">
          No such case
        </h1>
        <p className="max-w-md text-[13px] leading-relaxed text-fg-muted">
          That case file could not be loaded. It may have been removed, or the backend
          may not be running.
        </p>
        <Link
          href="/"
          className="mt-2 rounded-[6px] bg-accent px-4 py-2 text-[13px] font-medium text-bg transition-all hover:brightness-110"
        >
          Back to the console
        </Link>
      </main>
    </>
  );
}
