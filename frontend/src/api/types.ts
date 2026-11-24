/**
 * Wire contracts for the Django API (spec section 8).
 * Mirrors backend/trips/api/contracts.py: change both together.
 */

export type RiskLevelKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel';
/** `unknown` means no forecast at the checkpoint ETA. It is never treated as Low. */
export type CheckpointLevel = RiskLevelKey | 'unknown';
export type Driver = 'wind' | 'rain' | 'snow';
export type SamplingInterval = 10 | 25 | 50;

export interface ErrorResponse {
  error: { code: string; message: string };
}

// --- GET /api/geocode?q= ----------------------------------------------------------------------

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

export interface GeocodeResponse {
  /** Up to five suggestions. */
  results: Place[];
}

// --- POST /api/trips/plan ---------------------------------------------------------------------

export interface PlanRequest {
  origin: Place;
  destination: Place;
  /** ISO 8601 with a UTC offset. */
  departure: string;
  load_lb: number;
  interval_mi: SamplingInterval;
}

export interface Checkpoint {
  index: number;
  lat: number;
  lon: number;
  mile: number;
  eta: string;
  wind_mph: number | null;
  gust_mph: number | null;
  rain_in_hr: number | null;
  snow_in_hr: number | null;
  level: CheckpointLevel;
  driver: Driver | null;
}

export type MilesByLevel = Record<RiskLevelKey, number>;

export interface RouteSummary {
  miles_by_level: MilesByLevel;
  avg_risk: number;
  unknown_checkpoints: number;
}

export interface Route {
  id: string;
  rank: number;
  reason: string;
  distance_mi: number;
  duration_s: number;
  arrival: string;
  /** Encoded polyline. */
  geometry: string;
  summary: RouteSummary;
  checkpoints: Checkpoint[];
}

/** [min_lon, min_lat, max_lon, max_lat] */
export type BBox = [number, number, number, number];

export interface PlanResponse {
  recommended_route_id: string;
  no_safe_route: boolean;
  routes: Route[];
  corridor: { bbox: BBox };
}

// --- POST /api/trips/heatmap ------------------------------------------------------------------

export interface HeatmapRequest {
  bbox: BBox;
  route_geometries: string[];
  start: string;
  load_lb: number;
}

export interface HeatmapResponse {
  /** Parallel arrays: grid point i is at (lats[i], lons[i]). */
  grid: { lats: number[]; lons: number[] };
  /** Always 49: departure-relative hours 0 to 48. */
  hours: number;
  /** Per hour, per grid point: level 0-4, or null when the forecast is unavailable. */
  risk: (number | null)[][];
  wind: (number | null)[][];
  rain: (number | null)[][];
  snow: (number | null)[][];
}
