import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { RunSummary } from "@/types/api";
import { Badge } from "@/components/ui/primitives";
import { formatUTC, shortHash } from "@/lib/utils";

const TONE: Record<string, string> = {
  strong: "danger",
  probable: "accent",
  weak: "neutral",
  insufficient_evidence: "neutral",
};

export function RecentCases({ runs }: { runs: RunSummary[] }) {
  if (!runs.length) {
    return (
      <div className="panel p-6 text-center text-[12px] text-fg-muted">
        No cases yet. Upload a SAR scene above to open the first one.
      </div>
    );
  }

  return (
    <div className="panel divide-y divide-[var(--color-border)] overflow-hidden">
      {runs.map((r) => (
        <Link
          key={r.id}
          href={`/case/${r.id}`}
          className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-sunken"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-[family-name:var(--font-mono)] text-[12px] text-fg">
                {r.id.slice(0, 8)}
              </span>
              {r.conclusion && (
                <Badge tone={(TONE[r.conclusion] ?? "neutral") as any}>
                  {r.conclusion.replace(/_/g, " ")}
                </Badge>
              )}
              {!r.is_georeferenced && <Badge tone="neutral">no georef</Badge>}
            </div>
            <div className="mt-1 font-[family-name:var(--font-mono)] text-[10px] text-fg-dim">
              {formatUTC(r.created_at)} · {r.spills_detected} region
              {r.spills_detected === 1 ? "" : "s"} · {r.suspects_ranked} candidate
              {r.suspects_ranked === 1 ? "" : "s"}
              {r.manifest_sha256 ? ` · ${shortHash(r.manifest_sha256, 8, 0)}` : ""}
            </div>
          </div>
          <ArrowUpRight
            size={13}
            className="shrink-0 text-fg-dim transition-colors group-hover:text-accent"
          />
        </Link>
      ))}
    </div>
  );
}
