import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventIntelligencePanel } from "@/components/events/event-intelligence-panel";
import type { ChangeEvent, EventIntelligence } from "@/types/api";

function sampleEvent(): ChangeEvent {
  return {
    id: "event-1",
    monitor_id: "monitor-1",
    analysis_id: "analysis-1",
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [-80.85, 35.22],
          [-80.84, 35.22],
          [-80.84, 35.23],
          [-80.85, 35.23],
          [-80.85, 35.22],
        ],
      ],
    },
    centroid: { type: "Point", coordinates: [-80.845, 35.225] },
    area_m2: 1400,
    perimeter_m: 210,
    confidence: 0.77,
    severity: "medium",
    mean_change_score: 0.4,
    max_change_score: 0.92,
    mean_abs_delta_ndvi: 0.2,
    mean_spectral_distance: 0.18,
    pixel_count: 36,
    first_detected_at: "2026-09-01T10:00:00Z",
    last_detected_at: "2026-09-01T10:00:00Z",
    status: "new",
    semantic_label: "vegetation_decrease",
    semantic_confidence: 0.72,
    semantic_abstained: false,
    properties: {},
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  };
}

function sampleIntelligence(withSemantic: boolean): EventIntelligence {
  return {
    event_id: "event-1",
    monitor_id: "monitor-1",
    analysis_id: "analysis-1",
    scientific_severity: "medium",
    change_confidence: 0.77,
    context_significance: "medium",
    exposure_significance: "low",
    roads: {
      intersecting_count: 1,
      intersecting_length_m: 32,
      nearby_count: 2,
      nearest_distance_m: 0,
      classes: { residential: 1 },
    },
    buildings: {
      intersecting_count: 1,
      intersection_area_m2: 42,
      nearby_count: 3,
      nearest_distance_m: 0,
    },
    waterways: {
      intersecting_count: 0,
      intersection_length_m: 0,
      nearby_count: 1,
      nearest_distance_m: 55,
      subtypes: ["stream"],
    },
    administrative_areas: [{ name: "Charlotte", admin_level: "8" }],
    population: {
      method: "areal_weighting",
      dataset: "worldpop",
      dataset_version: "2024",
      intersecting_units: 1,
      estimated_exposed_population: 25,
      largest_population_overlap: {
        source_feature_id: "pop-1",
        name: "Tract 1",
        source_population: 300,
        intersection_area_m2: 1200,
        source_area_m2: 9000,
        intersection_fraction: 0.1333,
        estimated_exposed_population: 40,
      },
      units: [
        {
          source_feature_id: "pop-1",
          name: "Tract 1",
          source_population: 300,
          intersection_area_m2: 1200,
          source_area_m2: 9000,
          intersection_fraction: 0.1333,
          estimated_exposed_population: 40,
        },
      ],
    },
    land_cover: {
      provider: "esa",
      dataset: "worldcover",
      dataset_version: "v200",
      dominant_class: "Tree cover",
      dominant_fraction: 0.55,
      nodata_fraction: 0,
      classes: [],
    },
    environment: {
      provider: "wdpa",
      dataset: "protected_areas",
      dataset_version: "2024-06",
      nearby_buffer_m: 500,
      intersecting_count: 0,
      intersection_area_m2: 0,
      nearby_count: 0,
      protected_area_fraction: 0,
      nearest_distance_m: null,
      designations: [],
      features: [],
    },
    significance_factors: [],
    semantic: withSemantic
      ? {
          id: "semantic-1",
          change_event_id: "event-1",
          change_analysis_id: "analysis-1",
          before_prepared_observation_id: "before-1",
          after_prepared_observation_id: "after-1",
          semantic_label: "vegetation_decrease",
          semantic_confidence: 0.72,
          abstained: false,
          model_name: "torchgeo_resnet18_sentinel2_rgb_moco",
          model_version: "resnet18_sentinel2_rgb_moco-e3a335e3",
          inference_method: "hybrid_rule_v1",
          before_land_cover: "Tree cover",
          after_land_cover: null,
          before_ndvi_mean: 0.64,
          after_ndvi_mean: 0.44,
          ndvi_delta: -0.2,
          before_ndwi_mean: 0.18,
          after_ndwi_mean: 0.15,
          ndwi_delta: -0.03,
          before_nbr_mean: 0.33,
          after_nbr_mean: 0.27,
          nbr_delta: -0.06,
          before_built_up_score: 0.11,
          after_built_up_score: 0.16,
          built_up_delta: 0.05,
          embedding_distance: 0.25,
          valid_pixel_coverage: 0.84,
          explanation: ["Semantic evidence confidence reflects agreement and signal strength; it is not a calibrated probability."],
          evidence: {},
          created_at: "2026-09-01T11:00:00Z",
          updated_at: "2026-09-01T11:00:00Z",
        }
      : null,
  };
}

describe("EventIntelligencePanel semantic section", () => {
  it("renders semantic label and confidence disclaimer", () => {
    render(
      <EventIntelligencePanel
        loading={false}
        intelligence={sampleIntelligence(true)}
        event={sampleEvent()}
      />,
    );

    expect(screen.getByText(/Semantic Change/i)).toBeInTheDocument();
    expect(screen.getByText(/vegetation_decrease/i)).toBeInTheDocument();
    expect(screen.getByText(/not a calibrated probability/i)).toBeInTheDocument();
    expect(screen.getByText(/do not by themselves establish cause/i)).toBeInTheDocument();
  });

  it("shows not-computed state when semantic analysis is absent", () => {
    render(
      <EventIntelligencePanel
        loading={false}
        intelligence={sampleIntelligence(false)}
        event={sampleEvent()}
      />,
    );

    expect(screen.getByText(/has not been computed/i)).toBeInTheDocument();
  });
});
