"use client";

import Image from "next/image";

import { Panel, PanelHeader } from "@/components/ui";

type BeforeAfterViewerProps = {
  beforePreviewUrl: string | null;
  afterPreviewUrl: string | null;
  changeMaskUrl: string | null;
};

export function BeforeAfterViewer({ beforePreviewUrl, afterPreviewUrl, changeMaskUrl }: BeforeAfterViewerProps) {
  return (
    <Panel>
      <PanelHeader title="Before / After / Change" subtitle="Prepared observation previews and analysis mask" />
      <div className="grid gap-3 p-3 md:grid-cols-3">
        <Preview title="Before" imageUrl={beforePreviewUrl} />
        <Preview title="After" imageUrl={afterPreviewUrl} />
        <Preview title="Change Mask" imageUrl={changeMaskUrl} />
      </div>
    </Panel>
  );
}

function Preview({ title, imageUrl }: { title: string; imageUrl: string | null }) {
  return (
    <div className="rounded-md border border-argus-border bg-argus-panelMuted p-2">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-argus-muted">{title}</p>
      {imageUrl ? (
        <div className="relative aspect-square overflow-hidden rounded-md border border-argus-border bg-black/30">
          <Image src={imageUrl} alt={`${title} preview`} fill sizes="33vw" className="object-cover" unoptimized />
        </div>
      ) : (
        <div className="flex aspect-square items-center justify-center rounded-md border border-dashed border-argus-border text-xs text-argus-muted">
          Not available
        </div>
      )}
    </div>
  );
}
