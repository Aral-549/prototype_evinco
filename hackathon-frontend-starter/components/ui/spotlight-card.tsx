"use client";

import { useRef, useState, type MouseEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A panel with a soft light that follows the cursor — cheap way to make a
 * flat card feel alive. Use for feature cards, not everywhere (motion means
 * more when it's not on every single element).
 */
export function SpotlightCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 50, y: 50 });
  const [visible, setVisible] = useState(false);

  function handleMove(e: MouseEvent<HTMLDivElement>) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    setPos({
      x: ((e.clientX - rect.left) / rect.width) * 100,
      y: ((e.clientY - rect.top) / rect.height) * 100,
    });
  }

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      className={cn(
        "panel relative overflow-hidden p-6 transition-colors",
        className,
      )}
      style={{
        backgroundImage: visible
          ? `radial-gradient(240px circle at ${pos.x}% ${pos.y}%, color-mix(in oklch, var(--color-accent) 15%, transparent), transparent 70%)`
          : undefined,
      }}
    >
      {children}
    </div>
  );
}
