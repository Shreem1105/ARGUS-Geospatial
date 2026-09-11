"use client";

import Image from "next/image";
import { Expand, Shrink, SwitchCamera } from "lucide-react";
import { useMemo, useState } from "react";

import { Panel, PanelHeader } from "@/components/ui";
import { formatDateUtc } from "@/lib/format";

export type MonitorLayerMode =
  | "event_polygons"
  | "semantic_change"
  | "before_imagery"
  | "after_imagery"
  | "change_preview"
  | "change_mask";

type BeforeAfterViewerProps = {
  beforePreviewUrl: string | null;
  afterPreviewUrl: string | null;
  changePreviewUrl: string | null;
  changeMaskUrl: string | null;
  beforeItemId?: string | null;
  afterItemId?: string | null;
  beforeAcquiredAt?: string | null;
  afterAcquiredAt?: string | null;
  activeLayer: MonitorLayerMode;
  onLayerChange: (mode: MonitorLayerMode) => void;
};

type ComparisonMode = "split" | "side-by-side";

const LAYER_OPTIONS: Array<{ id: MonitorLayerMode; label: string }> = [
  { id: "event_polygons", label: "Event polygons" },
  { id: "semantic_change", label: "Semantic map" },
  { id: "before_imagery", label: "Before" },
  { id: "after_imagery", label: "After" },
  { id: "change_preview", label: "Change preview" },
  { id: "change_mask", label: "Change mask" },
];

export function BeforeAfterViewer({
  beforePreviewUrl,
  afterPreviewUrl,
  changePreviewUrl,
  changeMaskUrl,
  beforeItemId,
  afterItemId,
  beforeAcquiredAt,
  afterAcquiredAt,
  activeLayer,
  onLayerChange,
}: BeforeAfterViewerProps) {
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>("split");
  const [split, setSplit] = useState(50);
  const [swapped, setSwapped] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const leftImage = swapped ? afterPreviewUrl : beforePreviewUrl;
  const rightImage = swapped ? beforePreviewUrl : afterPreviewUrl;

  const selectedLayerPreview = useMemo(() => {
    if (activeLayer === "before_imagery") {
      return beforePreviewUrl;
    }
    if (activeLayer === "after_imagery") {
      return afterPreviewUrl;
    }
    if (activeLayer === "change_mask") {
      return changeMaskUrl;
    }
    if (activeLayer === "change_preview") {
      return changePreviewUrl;
    }
    return null;
  }, [activeLayer, afterPreviewUrl, beforePreviewUrl, changeMaskUrl, changePreviewUrl]);

  const content = (
    <>
      <div className="border-b border-argus-border px-3 py-2 text-[11px] text-argus-muted">
        <p>Before: {beforeItemId ?? "—"} · {formatDateUtc(beforeAcquiredAt)}</p>
        <p>After: {afterItemId ?? "—"} · {formatDateUtc(afterAcquiredAt)}</p>
      </div>

      <div className="argus-scroll flex flex-wrap gap-1 border-b border-argus-border px-3 py-2 text-xs">
        {LAYER_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`rounded-md border px-2 py-1 ${
              activeLayer === option.id
                ? "border-argus-accent bg-argus-accent/15 text-argus-text"
                : "border-argus-border bg-argus-panel text-argus-muted"
            }`}
            onClick={() => onLayerChange(option.id)}
          >
            {option.label}
          </button>
        ))}

        <button
          type="button"
          onClick={() => setComparisonMode((current) => (current === "split" ? "side-by-side" : "split"))}
          className="ml-auto rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-argus-muted"
          disabled={!beforePreviewUrl || !afterPreviewUrl}
        >
          {comparisonMode === "split" ? "Side-by-side" : "Split"}
        </button>
        <button
          type="button"
          onClick={() => setSwapped((current) => !current)}
          className="rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-argus-muted"
          disabled={!beforePreviewUrl || !afterPreviewUrl}
        >
          <SwitchCamera size={12} className="inline" /> Swap
        </button>
      </div>

      <div className="grid gap-3 p-3 xl:grid-cols-[2fr,1fr]">
        <div className="argus-panel-muted p-2">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-argus-muted">Before / After</p>
          {comparisonMode === "split" && leftImage && rightImage ? (
            <SplitView leftImage={leftImage} rightImage={rightImage} split={split} onSplitChange={setSplit} />
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              <Preview title={swapped ? "After" : "Before"} imageUrl={leftImage} />
              <Preview title={swapped ? "Before" : "After"} imageUrl={rightImage} />
            </div>
          )}
        </div>

        <div className="argus-panel-muted p-2">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-argus-muted">Selected layer</p>
          <Preview title={activeLayer.replaceAll("_", " ")} imageUrl={selectedLayerPreview} />
        </div>
      </div>
    </>
  );

  return (
    <Panel>
      <PanelHeader
        title="Imagery Comparison"
        subtitle="Real prepared previews only; no synthetic alignment"
        actions={
          <button type="button" onClick={() => setFullscreen((current) => !current)} className="argus-control">
            {fullscreen ? <Shrink size={12} /> : <Expand size={12} />}
            {fullscreen ? "Exit fullscreen" : "Fullscreen"}
          </button>
        }
      />

      {content}

      {fullscreen ? (
        <div className="fixed inset-0 z-[55] overflow-y-auto bg-black/85 p-4" role="dialog" aria-label="Fullscreen imagery comparison">
          <div className="mx-auto w-full max-w-7xl rounded-xl border border-argus-border bg-argus-bg p-2">
            <div className="mb-2 flex justify-end">
              <button type="button" onClick={() => setFullscreen(false)} className="argus-control">
                <Shrink size={12} /> Close
              </button>
            </div>
            {content}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function SplitView({
  leftImage,
  rightImage,
  split,
  onSplitChange,
}: {
  leftImage: string;
  rightImage: string;
  split: number;
  onSplitChange: (value: number) => void;
}) {
  return (
    <div>
      <div className="relative aspect-video overflow-hidden rounded-md border border-argus-border bg-black/35">
        <Image src={leftImage} alt="Before imagery" fill sizes="66vw" className="object-cover" unoptimized />
        <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
          <Image src={rightImage} alt="After imagery" fill sizes="66vw" className="object-cover" unoptimized />
        </div>
        <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/55 px-1.5 py-0.5 text-[11px]">Before</div>
        <div className="pointer-events-none absolute bottom-2 right-2 rounded bg-black/55 px-1.5 py-0.5 text-[11px]">After</div>
        <div className="pointer-events-none absolute bottom-0 top-0 w-[2px] bg-argus-accent" style={{ left: `${split}%` }} />
      </div>

      <label className="mt-2 block text-[11px] text-argus-muted">
        Split control
        <input
          type="range"
          min={0}
          max={100}
          value={split}
          onChange={(event) => onSplitChange(Number(event.target.value))}
          className="mt-1 w-full"
          aria-label="Before and after split control"
        />
      </label>
    </div>
  );
}

function Preview({ title, imageUrl }: { title: string; imageUrl: string | null }) {
  return (
    <div className="rounded-md border border-argus-border bg-argus-panelMuted p-2">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-argus-muted">{title}</p>
      {imageUrl ? (
        <div className="relative aspect-video overflow-hidden rounded-md border border-argus-border bg-black/30">
          <Image src={imageUrl} alt={`${title} preview`} fill sizes="33vw" className="object-cover" unoptimized />
        </div>
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-md border border-dashed border-argus-border text-xs text-argus-muted">
          Not available
        </div>
      )}
    </div>
  );
}
