import type { GeoJsonGeometry, GeoJsonPoint, GeoJsonPolygon } from "@/types/geojson";

export type MonitorStatus = "active" | "paused" | "archived";
export type ChangeEventSeverity = "low" | "medium" | "high" | "critical";
export type ChangeEventStatus = "new" | "reviewed" | "dismissed" | "confirmed";
export type SemanticLabel =
  | "vegetation_decrease"
  | "vegetation_increase"
  | "built_area_increase"
  | "built_area_decrease"
  | "water_expansion"
  | "water_contraction"
  | "bare_ground_increase"
  | "bare_ground_decrease"
  | "mixed_change"
  | "uncertain";
export type AnalysisStatus = "processing" | "ready" | "failed";
export type PreparedStatus = "processing" | "ready" | "failed";
export type MonitorRunStatus = "started" | "succeeded" | "no_new_imagery" | "partial" | "failed" | "cancelled";
export type MonitorRunType = "manual" | "scheduled";

export interface Monitor {
  id: string;
  name: string;
  description: string | null;
  geometry: GeoJsonPolygon;
  monitor_type: string;
  sensitivity: number;
  minimum_change_area_m2: number;
  status: MonitorStatus;
  created_at: string;
  updated_at: string;
  last_analyzed_at: string | null;
}

export interface MonitorSpatialSummary {
  monitor_id: string;
  name: string;
  status: MonitorStatus;
  geometry_type: string;
  srid: number;
  area_m2: number;
  area_km2: number;
  centroid: GeoJsonPoint;
  bounding_box: {
    min_lon: number;
    min_lat: number;
    max_lon: number;
    max_lat: number;
  };
}

export interface ObservationAsset {
  href: string;
  media_type: string | null;
  roles: string[] | null;
  title: string | null;
}

export interface SatelliteObservation {
  id: string;
  monitor_id: string;
  provider: string;
  collection: string;
  item_id: string;
  platform: string | null;
  sensor: string | null;
  acquired_at: string;
  cloud_cover: number | null;
  geometry: GeoJsonGeometry;
  bbox: number[] | null;
  thumbnail_url: string | null;
  assets: Record<string, ObservationAsset>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface PreparedObservation {
  id: string;
  monitor_id: string;
  observation_id: string;
  status: PreparedStatus;
  storage_uri: string | null;
  valid_mask_uri: string | null;
  preview_uri: string | null;
  crs: string | null;
  resolution_m: number | null;
  width: number | null;
  height: number | null;
  band_names: string[];
  cloud_fraction: number | null;
  valid_fraction: number | null;
  nodata_value: number | null;
  processing_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  observation: {
    id: string;
    item_id: string;
    provider: string;
    collection: string;
    platform: string | null;
    acquired_at: string;
    cloud_cover: number | null;
  };
}

export interface ChangeAnalysis {
  id: string;
  monitor_id: string;
  before_prepared_id: string;
  after_prepared_id: string;
  status: AnalysisStatus;
  algorithm: string;
  algorithm_version: string;
  change_score_uri: string | null;
  change_mask_uri: string | null;
  valid_comparison_mask_uri: string | null;
  preview_uri: string | null;
  threshold: number;
  minimum_change_area_m2: number;
  changed_pixel_count: number | null;
  valid_pixel_count: number | null;
  changed_fraction: number | null;
  changed_area_m2: number | null;
  mean_change_score: number | null;
  max_change_score: number | null;
  statistics: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ChangeEvent {
  id: string;
  monitor_id: string;
  analysis_id: string;
  geometry: GeoJsonPolygon;
  centroid: GeoJsonPoint;
  area_m2: number;
  perimeter_m: number;
  confidence: number;
  severity: ChangeEventSeverity;
  mean_change_score: number;
  max_change_score: number;
  mean_abs_delta_ndvi: number | null;
  mean_spectral_distance: number | null;
  pixel_count: number;
  first_detected_at: string;
  last_detected_at: string;
  status: ChangeEventStatus;
  semantic_label: SemanticLabel | null;
  semantic_confidence: number | null;
  semantic_abstained: boolean | null;
  properties: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ChangeEventSemanticAnalysis {
  id: string;
  change_event_id: string;
  change_analysis_id: string;
  before_prepared_observation_id: string;
  after_prepared_observation_id: string;
  semantic_label: SemanticLabel;
  semantic_confidence: number;
  abstained: boolean;
  model_name: string;
  model_version: string;
  inference_method: string;
  before_land_cover: string | null;
  after_land_cover: string | null;
  before_ndvi_mean: number | null;
  after_ndvi_mean: number | null;
  ndvi_delta: number | null;
  before_ndwi_mean: number | null;
  after_ndwi_mean: number | null;
  ndwi_delta: number | null;
  before_nbr_mean: number | null;
  after_nbr_mean: number | null;
  nbr_delta: number | null;
  before_built_up_score: number | null;
  after_built_up_score: number | null;
  built_up_delta: number | null;
  embedding_distance: number | null;
  valid_pixel_coverage: number | null;
  explanation: string[];
  evidence: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EventSemanticComputeResponse {
  computed: boolean;
  summary: ChangeEventSemanticAnalysis;
}

export interface AnalysisSemanticComputeResponse {
  analysis_id: string;
  event_count: number;
  computed: number;
  reused: number;
  failed: number;
  elapsed_seconds: number;
}

export interface ContextFeature {
  id: string;
  monitor_id: string;
  provider: string;
  provider_feature_id: string;
  feature_type: "road" | "building" | "waterway" | "administrative";
  feature_subtype: string | null;
  name: string | null;
  geometry: GeoJsonGeometry;
  properties: Record<string, unknown>;
  source_updated_at: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
}

export interface ContextSummary {
  monitor_id: string;
  total_features: number;
  by_type: Record<string, number>;
  road_classes: Record<string, number>;
  providers: string[];
  attribution: string;
  last_fetched_at: string | null;
}

export interface EventImpactSummary {
  event_id: string;
  monitor_id: string;
  analysis_id: string;
  scientific_severity: ChangeEventSeverity;
  context_significance: "low" | "medium" | "high";
  impact_relationship_count: number;
  roads: {
    intersecting_count: number;
    intersecting_length_m: number;
    nearby_count: number;
    nearest_distance_m: number | null;
    classes: Record<string, number>;
  };
  buildings: {
    intersecting_count: number;
    intersection_area_m2: number;
    nearby_count: number;
    nearest_distance_m: number | null;
  };
  waterways: {
    intersecting_count: number;
    intersection_length_m: number;
    nearby_count: number;
    nearest_distance_m: number | null;
    subtypes: string[];
  };
  administrative_areas: Array<{ name: string | null; admin_level: string | null }>;
}

export interface EventExposureSummary {
  event_id: string;
  monitor_id: string;
  analysis_id: string;
  scientific_severity: ChangeEventSeverity;
  population: {
    method: "areal_weighting";
    dataset: string;
    dataset_version: string;
    intersecting_units: number;
    estimated_exposed_population: number;
    largest_population_overlap: {
      source_feature_id: string;
      name: string | null;
      source_population: number | null;
      intersection_area_m2: number;
      source_area_m2: number;
      intersection_fraction: number;
      estimated_exposed_population: number | null;
    } | null;
    units: Array<{
      source_feature_id: string;
      name: string | null;
      source_population: number | null;
      intersection_area_m2: number;
      source_area_m2: number;
      intersection_fraction: number;
      estimated_exposed_population: number | null;
    }>;
  };
  land_cover: {
    provider: string;
    dataset: string;
    dataset_version: string;
    dominant_class: string | null;
    dominant_fraction: number;
    nodata_fraction: number;
    classes: Array<{
      class_code: number;
      class_name: string;
      area_m2: number;
      fraction_of_event: number;
    }>;
  };
  environment: {
    provider: string;
    dataset: string;
    dataset_version: string;
    nearby_buffer_m: number;
    intersecting_count: number;
    intersection_area_m2: number;
    protected_area_fraction: number;
    nearby_count: number;
    nearest_distance_m: number | null;
    designations: string[];
    features: Array<{
      source_feature_id: string;
      feature_type: string;
      feature_subtype: string | null;
      name: string | null;
      designation: string | null;
      manager: string | null;
      relationship_type: string;
      intersection_area_m2: number | null;
      intersection_fraction_of_event: number | null;
      distance_m: number;
    }>;
  };
  exposure_significance: "low" | "medium" | "high";
  significance_factors: Array<{
    factor: string;
    value: number;
    threshold: number;
    met: boolean;
  }>;
  computed_at: string;
}

export interface EventIntelligence {
  event_id: string;
  monitor_id: string;
  analysis_id: string;
  scientific_severity: ChangeEventSeverity;
  change_confidence: number;
  context_significance: "low" | "medium" | "high";
  exposure_significance: "low" | "medium" | "high";
  roads: EventImpactSummary["roads"];
  buildings: EventImpactSummary["buildings"];
  waterways: EventImpactSummary["waterways"];
  administrative_areas: EventImpactSummary["administrative_areas"];
  population: EventExposureSummary["population"];
  land_cover: EventExposureSummary["land_cover"];
  environment: EventExposureSummary["environment"];
  significance_factors: EventExposureSummary["significance_factors"];
  semantic: ChangeEventSemanticAnalysis | null;
}

export interface MonitorEventSummary {
  monitor_id: string;
  total_events: number;
  total_changed_area_m2: number;
  mean_confidence: number | null;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  latest_detected_at: string | null;
}

export interface MonitorImpactSummary {
  monitor_id: string;
  events_with_intersecting_roads: number;
  total_intersecting_road_length_m: number;
  events_with_intersecting_buildings: number;
  unique_intersecting_buildings: number;
  total_building_intersection_area_m2: number;
  events_near_waterways: number;
  administrative_areas_containing_events: Array<{ name: string | null; admin_level: string | null }>;
  total_impact_relationships: number;
  unique_context_features_in_impacts: number;
}

export interface MonitorExposureSummary {
  monitor_id: string;
  events_with_population_exposure: number;
  estimated_total_population_exposure_event_level_sum: number;
  events_intersecting_protected_areas: number;
  total_protected_area_intersection_m2: number;
  events_by_dominant_land_cover: Record<string, number>;
  events_by_exposure_significance: Record<string, number>;
}

export interface MonitorDatasetEntry {
  category: string;
  provider: string;
  dataset: string;
  dataset_version: string | null;
  fetched_at: string | null;
  feature_count: number;
  status: string;
  attribution: string | null;
}

export interface MonitorDatasets {
  monitor_id: string;
  datasets: MonitorDatasetEntry[];
}

export interface AnalysisJob {
  id: string;
  monitor_id: string;
  job_type: "monitor_run" | "analysis" | "context_refresh";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  celery_task_id: string | null;
  progress_stage: string;
  progress_percent: number;
  requested_parameters: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface MonitorRun {
  id: string;
  monitor_id: string;
  analysis_job_id: string;
  run_type: MonitorRunType;
  status: MonitorRunStatus;
  search_window_start: string | null;
  search_window_end: string | null;
  observations_found: number;
  observations_inserted: number;
  before_observation_id: string | null;
  after_observation_id: string | null;
  before_prepared_id: string | null;
  after_prepared_id: string | null;
  analysis_id: string | null;
  events_generated: number;
  semantics_computed: boolean;
  impacts_computed: boolean;
  exposures_computed: boolean;
  progress_log: Array<Record<string, unknown>>;
  requested_parameters: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  started_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface MonitorSchedule {
  monitor_id: string;
  enabled: boolean;
  interval_hours: number;
  cadence_minutes: number;
  lookback_days: number;
  max_cloud_cover: number | null;
  search_limit: number;
  auto_context_refresh: boolean;
  auto_population_refresh: boolean;
  auto_land_cover_refresh: boolean;
  auto_environment_refresh: boolean;
  threshold: number;
  minimum_change_area_m2: number | null;
  impact_nearby_buffer_m: number;
  environment_nearby_buffer_m: number;
  next_run_at: string | null;
  last_scan_at: string | null;
  last_run_at: string | null;
  last_enqueued_job_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkerHealth {
  status: string;
  redis: string;
  celery_worker: string;
  detail: string | null;
}

export interface ReadyHealth {
  status: string;
  database: string;
  postgis: string;
}

export interface RootStatus {
  name: string;
  status: string;
}
