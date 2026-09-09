import Link from "next/link";

import { EmptyState } from "@/components/ui";

export function CuratedExploreEmptyState() {
  return (
    <EmptyState
      title="No curated ARGUS case studies have been published yet."
      detail="Explore mode still uses real persisted ARGUS monitor/event intelligence data. Curated case stories will appear here when published."
      action={
        <Link
          href="/monitors"
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-text"
        >
          Open Monitor mode
        </Link>
      }
    />
  );
}
