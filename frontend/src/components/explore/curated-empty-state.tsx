import Link from "next/link";

import { EmptyState } from "@/components/ui";

export function CuratedExploreEmptyState() {
  return (
    <EmptyState
      title="No curated Explore scenarios loaded yet"
      detail="Explore mode is ready and connected to real ARGUS data. Once curated precomputed scenarios are published, they will appear here for instant public walkthroughs."
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
