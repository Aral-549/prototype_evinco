/**
 * Fixed, full-viewport film-grain layer. Pure CSS (see .noise-texture in
 * globals.css) — no image request, no perf cost. Drop it once near the root
 * of a page and every section under it gets a subtle "designed" texture
 * instead of a flat, generic fill.
 */
export function NoiseOverlay() {
  return (
    <div
      aria-hidden
      className="noise-texture pointer-events-none fixed inset-0 z-50"
    />
  );
}
