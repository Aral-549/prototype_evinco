import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * An uneven-cell grid — the direct antidote to "three identical rounded
 * cards in a row." Pass a `span` per item to break the rhythm on purpose.
 */
export function BentoGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-6", className)}>
      {children}
    </div>
  );
}

export function BentoItem({
  children,
  className,
  span = "sm:col-span-2",
}: {
  children: ReactNode;
  className?: string;
  span?: string;
}) {
  return <div className={cn("panel p-6", span, className)}>{children}</div>;
}
