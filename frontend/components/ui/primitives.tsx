"use client";

import { motion } from "framer-motion";
import { useRef, useState, type MouseEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Fixed film-grain layer. Drop once near the page root. */
export function NoiseOverlay() {
  return <div aria-hidden className="noise-texture pointer-events-none fixed inset-0 z-50" />;
}

/** A panel with a soft light that tracks the cursor. Used sparingly. */
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
      className={cn("panel relative overflow-hidden transition-colors", className)}
      style={{
        backgroundImage: visible
          ? `radial-gradient(260px circle at ${pos.x}% ${pos.y}%, color-mix(in oklch, var(--color-accent) 12%, transparent), transparent 70%)`
          : undefined,
      }}
    >
      {children}
    </div>
  );
}

/** Staggered word reveal. One deliberate motion moment per page, on the headline. */
export function TextReveal({
  text,
  className,
  as: Tag = "h1",
  delay = 0,
}: {
  text: string;
  className?: string;
  as?: keyof React.JSX.IntrinsicElements;
  delay?: number;
}) {
  const words = text.split(" ");
  return (
    <Tag className={className}>
      {words.map((word, i) => (
        <span key={i} className="inline-block overflow-hidden pb-1 pr-[0.25em] align-bottom">
          <motion.span
            className="inline-block"
            initial={{ y: "110%" }}
            animate={{ y: "0%" }}
            transition={{ duration: 0.6, delay: delay + i * 0.045, ease: [0.22, 1, 0.36, 1] }}
          >
            {word}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}

export function FadeIn({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

/** Uneven grid. The antidote to three identical cards in a row. */
export function BentoGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-6", className)}>{children}</div>
  );
}

export function Field({
  label,
  value,
  mono = true,
  className,
  title,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="label">{label}</div>
      <div
        title={title}
        className={cn(
          "mt-1 truncate text-[13px] text-fg",
          mono && "font-[family-name:var(--font-mono)]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

const TONES = {
  neutral: "border-border-bright bg-bg-sunken text-fg-muted",
  accent: "border-accent/45 bg-accent/12 text-accent",
  ocean: "border-accent-2/45 bg-accent-2/12 text-accent-2",
  danger: "border-danger/50 bg-danger/12 text-danger",
  success: "border-success/45 bg-success/12 text-success",
} as const;

export type Tone = keyof typeof TONES;

export function Badge({
  children,
  tone = "neutral",
  className,
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded border px-2 py-0.5",
        "font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.1em]",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Horizontal meter. Always paired with its numeric value, never colour alone. */
export function Meter({
  value,
  tone = "accent",
  className,
}: {
  value: number;
  tone?: Tone;
  className?: string;
}) {
  const pctValue = Math.max(0, Math.min(1, value)) * 100;
  const fill =
    tone === "danger"
      ? "var(--color-danger)"
      : tone === "ocean"
        ? "var(--color-accent-2)"
        : tone === "success"
          ? "var(--color-success)"
          : "var(--color-accent)";
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-bg-sunken", className)}
      role="meter"
      aria-valuenow={Math.round(pctValue)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <motion.div
        className="h-full rounded-full"
        style={{ background: fill }}
        initial={{ width: 0 }}
        animate={{ width: `${pctValue}%` }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

export function SectionHeading({
  index,
  title,
  hint,
  action,
}: {
  index: string;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4 border-b border-border pb-2">
      <div className="min-w-0">
        <div className="flex items-baseline gap-2.5">
          <span className="font-[family-name:var(--font-mono)] text-[11px] text-accent">
            {index}
          </span>
          <h2 className="font-[family-name:var(--font-display)] text-lg font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {hint && <p className="mt-0.5 text-[12px] leading-snug text-fg-muted">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
