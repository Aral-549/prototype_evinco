"use client";

import { useState } from "react";
import { Check, Copy, FileLock2, ShieldCheck } from "lucide-react";
import type { Dossier } from "@/types/api";
import { Field, SectionHeading, Badge } from "@/components/ui/primitives";
import { formatUTC, shortHash } from "@/lib/utils";

function HashRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const missing = !value || value === "unavailable";

  return (
    <div className="flex items-center justify-between gap-3 border-b border-border py-2 last:border-0">
      <span className="label shrink-0">{label}</span>
      <button
        disabled={missing}
        onClick={() => {
          navigator.clipboard?.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        }}
        title={missing ? "Not available" : value}
        className="group flex min-w-0 items-center gap-1.5 font-[family-name:var(--font-mono)] text-[11px] text-fg-muted transition-colors hover:text-fg disabled:cursor-default disabled:hover:text-fg-muted"
      >
        <span className="truncate">{missing ? "unavailable" : shortHash(value, 12, 8)}</span>
        {!missing &&
          (copied ? (
            <Check size={10} className="shrink-0 text-success" />
          ) : (
            <Copy size={10} className="shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
          ))}
      </button>
    </div>
  );
}

/**
 * The record that makes the rest of this page evidence rather than an assertion:
 * what was analysed, by which weights, under which parameters and seed. Re-running
 * with the same inputs must reproduce the same digests.
 */
export function ChainOfCustody({ dossier }: { dossier: Dossier }) {
  const m = dossier.chain_of_custody ?? {};
  const params = (m.parameters ?? {}) as Record<string, string>;
  const provenance = (m.metocean_provenance ?? []) as any[];
  const sealed = Boolean(m.manifest_sha256);

  return (
    <div>
      <SectionHeading
        index="08"
        title="Chain of custody"
        hint="Integrity digests over the exact inputs, weights and parameters. A third party re-running this case with the same seed obtains the same result, and an altered dossier fails verification."
        action={
          sealed ? (
            <Badge tone="success">
              <ShieldCheck size={9} />
              sealed
            </Badge>
          ) : (
            <Badge tone="neutral">not sealed</Badge>
          )
        }
      />

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="panel p-4">
          <div className="mb-2 flex items-center gap-1.5">
            <FileLock2 size={12} className="text-success" />
            <span className="label">Digests (SHA-256)</span>
          </div>
          <HashRow label="Input scene" value={m.input_sha256} />
          <HashRow label="Model weights" value={m.model_sha256} />
          <HashRow label="Content" value={m.content_sha256} />
          <HashRow label="Manifest" value={m.manifest_sha256} />
        </div>

        <div className="panel p-4">
          <div className="label mb-2.5">Provenance</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Model" value={m.model_name ?? "—"} mono={false} />
            <Field label="Version" value={m.model_version ?? "—"} />
            <Field label="Code commit" value={shortHash(m.code_version, 9, 0)} />
            <Field label="Issued" value={formatUTC(m.created_at)} />
            <Field label="Scene bytes" value={m.input_bytes?.toLocaleString?.() ?? "—"} />
            <Field label="Met-ocean samples" value={String(provenance.length)} />
          </div>
        </div>

        <div className="panel p-4">
          <div className="label mb-2.5">Sealed parameters</div>
          <div className="max-h-[188px] space-y-1 overflow-y-auto pr-1">
            {Object.entries(params).map(([k, v]) => (
              <div
                key={k}
                className="flex items-baseline justify-between gap-3 text-[11px]"
              >
                <span className="truncate text-fg-dim">{k.replace(/_/g, " ")}</span>
                <span className="shrink-0 font-[family-name:var(--font-mono)] text-fg-muted">
                  {String(v).length > 22 ? `${String(v).slice(0, 22)}…` : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-snug text-fg-dim">
        Scope: these are integrity digests, not signatures. They show a dossier is
        internally consistent with the data it names; they do not establish who produced
        it. Non-repudiation requires signing the manifest with an authority-held key,
        which is deliberately out of scope for this prototype.
      </p>
    </div>
  );
}
