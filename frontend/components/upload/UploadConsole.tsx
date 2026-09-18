"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, ChevronDown, FileImage, Loader2, MapPin, Play, Upload, Wind, X,
} from "lucide-react";
import {
  submitAnalysis, getStatus, OutOfDomainError, GeoreferenceGatedError, ApiError,
} from "@/services/api";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const STAGES = [
  { key: "detection", label: "Detection", hint: "U-Net over tiled SAR" },
  { key: "lookalike", label: "Screening", hint: "Oil vs look-alike" },
  { key: "drift", label: "Drift ensemble", hint: "Backward Monte Carlo" },
  { key: "ais_attribution", label: "Attribution", hint: "Bayesian over AIS" },
  { key: "completed", label: "Sealed", hint: "Chain of custody" },
];

const ACCEPTED = [".png", ".jpg", ".jpeg", ".tif", ".tiff"];
const MAX_BYTES = 100 * 1024 * 1024;

/** Preset bounding boxes so a demo does not require typing four coordinates. */
const PRESETS = [
  { name: "Mumbai approaches", box: ["71.90", "18.90", "72.30", "19.30"] },
  { name: "Gulf of Kutch", box: ["69.00", "22.30", "69.60", "22.80"] },
  { name: "Chennai offshore", box: ["80.30", "12.90", "80.80", "13.40"] },
];

export function UploadConsole() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);

  const [bbox, setBbox] = useState(["", "", "", ""]);
  const [met, setMet] = useState({ wind: "", windDir: "", curr: "", currDir: "", hours: "24" });

  const choose = useCallback((f: File | null) => {
    setError(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      setError({
        title: "Unsupported file type",
        body: `This console accepts SAR scenes as ${ACCEPTED.join(", ")}. GeoTIFF is preferred because its tags carry the georeference the attribution stage needs.`,
      });
      return;
    }
    if (f.size > MAX_BYTES) {
      setError({
        title: "File too large",
        body: `${(f.size / 1024 / 1024).toFixed(0)} MB exceeds the 100 MB upload limit.`,
      });
      return;
    }
    setFile(f);
    if (/\.(png|jpe?g)$/i.test(f.name)) setPreview(URL.createObjectURL(f));
    else setPreview(null);
  }, []);

  async function run() {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setStage("detection");

    try {
      const { id } = await submitAnalysis({
        image: file,
        bboxMinLon: bbox[0], bboxMinLat: bbox[1],
        bboxMaxLon: bbox[2], bboxMaxLat: bbox[3],
        windSpeed: met.wind, windDirection: met.windDir,
        currentSpeed: met.curr, currentDirection: met.currDir,
        durationHours: met.hours,
      });

      // The backend runs synchronously when no Celery worker is up, so the run may
      // already be finished by the time this returns. Poll regardless: it costs one
      // request and covers both modes.
      for (let i = 0; i < 150; i++) {
        const s = await getStatus(id);
        setStage(s.stage);
        if (s.status === "completed" || s.status === "failed") break;
        await new Promise((r) => setTimeout(r, 1200));
      }
      router.push(`/case/${id}`);
    } catch (e) {
      if (e instanceof OutOfDomainError) {
        setError({
          title: "Rejected by the SAR domain gate",
          body: e.message,
        });
      } else if (e instanceof GeoreferenceGatedError) {
        setError({ title: "Georeference required", body: e.message });
      } else {
        setError({
          title: "Analysis failed",
          body: e instanceof ApiError ? e.message : "The backend could not be reached. Is the Django server running on port 8000?",
        });
      }
      setBusy(false);
      setStage(null);
    }
  }

  const activeIndex = STAGES.findIndex((s) => s.key === stage);

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
      {/* ── Drop zone ─────────────────────────────────────── */}
      <div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            choose(e.dataTransfer.files?.[0] ?? null);
          }}
          onClick={() => !busy && inputRef.current?.click()}
          className={cn(
            "panel relative flex min-h-[236px] cursor-pointer flex-col items-center justify-center gap-3 overflow-hidden p-6 text-center transition-colors",
            dragging && "border-accent bg-accent/[0.06]",
            busy && "cursor-default opacity-60",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED.join(",")}
            className="hidden"
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />

          {preview && (
            // A local blob: URL for the file the operator just picked. There is no
            // remote source for next/image to optimise.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={preview}
              alt=""
              aria-hidden
              className="absolute inset-0 h-full w-full object-cover opacity-20"
            />
          )}

          <div className="relative">
            {file ? (
              <FileImage size={26} className="text-accent" />
            ) : (
              <Upload size={26} className={cn(dragging ? "text-accent" : "text-fg-dim")} />
            )}
          </div>

          <div className="relative">
            {file ? (
              <>
                <div className="text-[14px] font-medium">{file.name}</div>
                <div className="mt-0.5 font-[family-name:var(--font-mono)] text-[11px] text-fg-dim">
                  {(file.size / 1024 / 1024).toFixed(1)} MB
                </div>
              </>
            ) : (
              <>
                <div className="text-[14px] font-medium">Drop a Sentinel-1 SAR scene</div>
                <div className="mt-1 text-[12px] text-fg-muted">
                  GeoTIFF preferred · PNG and JPEG accepted with manual coordinates
                </div>
              </>
            )}
          </div>

          {file && !busy && (
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); setPreview(null); }}
              className="relative mt-1 flex items-center gap-1 text-[11px] text-fg-dim transition-colors hover:text-fg"
            >
              <X size={10} /> remove
            </button>
          )}
        </div>

        {/* ── Stage progress ──────────────────────────────── */}
        <AnimatePresence>
          {busy && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="panel mt-3 p-4">
                <div className="space-y-2">
                  {STAGES.map((s, i) => {
                    const done = activeIndex > i;
                    const active = activeIndex === i;
                    return (
                      <div key={s.key} className="flex items-center gap-3">
                        <div
                          className={cn(
                            "relative grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px]",
                            done && "border-success/60 bg-success/15 text-success",
                            active && "border-accent bg-accent/15 text-accent",
                            !done && !active && "border-border text-fg-dim",
                          )}
                        >
                          {active ? <Loader2 size={10} className="animate-spin" /> : i + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div
                            className={cn(
                              "text-[12px]",
                              active ? "text-fg" : done ? "text-fg-muted" : "text-fg-dim",
                            )}
                          >
                            {s.label}
                          </div>
                        </div>
                        <div
                          className={cn(
                            "relative h-1 w-20 overflow-hidden rounded-full bg-bg-sunken",
                            active && "sweeping",
                          )}
                        >
                          {done && <div className="h-full w-full bg-success/50" />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <div className="panel mt-3 border-danger/40 p-4">
            <div className="mb-1.5 flex items-center gap-1.5">
              <AlertTriangle size={12} className="text-danger" />
              <span className="label text-danger">{error.title}</span>
            </div>
            <p className="text-[12px] leading-relaxed text-fg-muted">{error.body}</p>
          </div>
        )}
      </div>

      {/* ── Parameters ────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="panel p-4">
          <div className="mb-2.5 flex items-center gap-1.5">
            <MapPin size={12} className="text-accent-2" />
            <span className="label">Georeference</span>
          </div>

          <div className="mb-3 flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                onClick={() => setBbox(p.box)}
                className="rounded border border-border px-2 py-1 text-[10px] text-fg-muted transition-colors hover:border-accent/50 hover:text-accent"
              >
                {p.name}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            {["min lon", "min lat", "max lon", "max lat"].map((label, i) => (
              <label key={label} className="block">
                <span className="label">{label}</span>
                <input
                  value={bbox[i]}
                  onChange={(e) => {
                    const next = [...bbox];
                    next[i] = e.target.value;
                    setBbox(next);
                  }}
                  placeholder="—"
                  inputMode="decimal"
                  className="mt-1 w-full rounded border border-border bg-bg-sunken px-2 py-1.5 font-[family-name:var(--font-mono)] text-[12px] outline-none transition-colors focus:border-accent"
                />
              </label>
            ))}
          </div>
          <p className="mt-2.5 text-[10px] leading-snug text-fg-dim">
            Optional for GeoTIFF. Without coordinates the pipeline still detects the
            slick but withholds drift and attribution rather than invent a position.
          </p>
        </div>

        <div className="panel overflow-hidden">
          <button
            onClick={() => setAdvanced(!advanced)}
            className="flex w-full items-center justify-between gap-2 p-4 text-left transition-colors hover:bg-bg-sunken"
          >
            <span className="flex items-center gap-1.5">
              <Wind size={12} className="text-accent-2" />
              <span className="label">Met-ocean override</span>
            </span>
            <ChevronDown
              size={13}
              className={cn("text-fg-dim transition-transform", advanced && "rotate-180")}
            />
          </button>

          <AnimatePresence initial={false}>
            {advanced && (
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: "auto" }}
                exit={{ height: 0 }}
                transition={{ duration: 0.22 }}
                className="overflow-hidden"
              >
                <div className="border-t border-border p-4">
                  <div className="grid grid-cols-2 gap-2">
                    {([
                      ["wind", "wind m/s"],
                      ["windDir", "wind from °"],
                      ["curr", "current m/s"],
                      ["currDir", "current to °"],
                      ["hours", "hindcast h"],
                    ] as const).map(([key, label]) => (
                      <label key={key} className="block">
                        <span className="label">{label}</span>
                        <input
                          value={(met as any)[key]}
                          onChange={(e) => setMet({ ...met, [key]: e.target.value })}
                          placeholder="auto"
                          inputMode="decimal"
                          className="mt-1 w-full rounded border border-border bg-bg-sunken px-2 py-1.5 font-[family-name:var(--font-mono)] text-[12px] outline-none transition-colors focus:border-accent"
                        />
                      </label>
                    ))}
                  </div>
                  <p className="mt-2.5 text-[10px] leading-snug text-fg-dim">
                    Left blank, the hourly field is fetched from Open-Meteo and re-sampled
                    along the trajectory. An explicit override is held constant, because
                    you asserted those conditions.
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <button
          onClick={run}
          disabled={!file || busy}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-[6px] px-4 py-3 text-[13px] font-medium transition-all",
            file && !busy
              ? "bg-accent text-bg hover:brightness-110"
              : "cursor-not-allowed bg-bg-raised text-fg-dim",
          )}
        >
          {busy ? (
            <>
              <Loader2 size={13} className="animate-spin" /> Analysing…
            </>
          ) : (
            <>
              <Play size={13} /> Run forensic analysis
            </>
          )}
        </button>

        <div className="flex flex-wrap gap-1.5">
          <Badge tone="neutral">Layer 1 · SAR gate</Badge>
          <Badge tone="neutral">Layer 2 · look-alike</Badge>
          <Badge tone="neutral">Layer 3 · georeference</Badge>
        </div>
      </div>
    </div>
  );
}
