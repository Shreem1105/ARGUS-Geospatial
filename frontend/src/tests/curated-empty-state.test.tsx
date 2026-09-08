import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CuratedExploreEmptyState } from "@/components/explore/curated-empty-state";

describe("CuratedExploreEmptyState", () => {
  it("renders non-fake explore fallback", () => {
    render(<CuratedExploreEmptyState />);
    expect(screen.getByText(/No curated Explore scenarios loaded yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Monitor mode/i })).toHaveAttribute("href", "/monitors");
  });
});
