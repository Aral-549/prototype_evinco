import type { ReactNode } from "react";

/**
 * Infinite horizontal scroll strip — good for a row of sponsor logos, tech
 * stack badges, or a repeated tagline. Pure CSS animation, no JS cost.
 */
export function Marquee({ children }: { children: ReactNode }) {
  return (
    <div className="group relative overflow-hidden py-4 [mask-image:linear-gradient(to_right,transparent,black_10%,black_90%,transparent)]">
      <div className="flex w-max animate-[marquee_28s_linear_infinite] gap-12 group-hover:[animation-play-state:paused]">
        <div className="flex gap-12">{children}</div>
        <div className="flex gap-12" aria-hidden>
          {children}
        </div>
      </div>
      <style>{`
        @keyframes marquee {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
