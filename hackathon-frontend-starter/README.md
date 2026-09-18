# Hackathon Frontend Starter

A Next.js + Tailwind starter built to avoid the "default AI website" look —
Inter-only type, an indigo/purple gradient, a centered hero with three rounded
cards below it. It comes pre-wired with a different font pair, a hand-picked
color palette, and a handful of components that give a hackathon build a
premium feel fast: a spotlight card, an uneven bento grid, an infinite
marquee, a staggered text reveal, and a film-grain overlay.

Pairs with the `hackathon-frontend-design` Claude skill — ask Claude to build
your hackathon frontend and it will scaffold from this project instead of a
bare `create-next-app`.

## Run it

```bash
npm install
npm run dev
```

Open http://localhost:3000. You should see a dark, amber-accented landing
page, not a white page with a purple gradient — that's the point.

## Reskin it for a new hackathon (5 minutes)

Everything that defines the look lives in two places:

1. **`app/globals.css`** — the `:root` block at the top. Change
   `--color-bg`, `--color-fg`, `--color-accent`, `--color-accent-2` to a new
   OKLCH palette (generate one at [realtimecolors.com](https://realtimecolors.com)
   or [coolors.co](https://coolors.co), then convert to OKLCH — or just hand-tune
   the values, they're `lightness chroma hue`).
2. **`app/layout.tsx`** — swap `Bricolage_Grotesque` / `Instrument_Sans` /
   `Space_Mono` for a different `next/font/google` pair. Don't reach for
   Inter alone — pick a display font with actual character. Good options:
   `Fraunces`, `Newsreader`, `Space_Grotesk`, `Clash_Display` (via
   [Fontshare](https://fontshare.com), not Google Fonts), `Bricolage_Grotesque`.

That's it — every component pulls from these tokens, so the whole site
re-themes itself.

## What's in here

- `app/globals.css` — design tokens (color, font, radius) + the noise texture
  and scrollbar/selection styling
- `app/layout.tsx` — font loading via `next/font/google` (self-hosted at
  build time, zero runtime font requests)
- `components/hero.tsx` — an asymmetric hero (off-center copy + a metric
  panel), not a dead-centered stack
- `components/navbar.tsx` — simple sticky nav
- `components/ui/spotlight-card.tsx` — a card with cursor-tracked light
- `components/ui/bento-grid.tsx` — uneven-span grid instead of 3 equal cards
- `components/ui/marquee.tsx` — infinite scroll strip, pure CSS
- `components/ui/text-reveal.tsx` — staggered headline reveal + scroll-in
  fade helper, both via Framer Motion
- `components/ui/noise-overlay.tsx` — the film-grain layer

## Extending with a component library

For anything beyond what's here, layer in [shadcn/ui](https://ui.shadcn.com)
for accessible primitives (dialogs, dropdowns, forms) and
[Aceternity UI](https://ui.aceternity.com) or [Magic UI](https://magicui.design)
for more animated flourishes. Always re-theme their color/font classes to the
tokens above — pasting them in unstyled just trades one recognizable default
look for another.

## Before you demo, check:

- Every screen uses the same 2 fonts and the same color tokens — nothing
  left at a library default
- The hero would be recognizable as *this* product, not swappable onto any
  other site with different text
- At least one non-centered, non-triptych layout choice
- At least one real motion/interaction detail
- It still holds up at phone width
