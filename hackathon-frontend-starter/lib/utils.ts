import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind classes without collisions. Use this everywhere instead of
 * template-stringing classNames together.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
