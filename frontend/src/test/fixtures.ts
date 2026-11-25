import type { HeatmapResponse, PlanResponse, Route } from '../api/types';

export const testRoute: Route = {
  id: 'r1',
  name: 'Route A',
  rank: 2,
  reason: 'More High miles than Route B.',
  distance_mi: 100,
  duration_s: 7200,
  arrival: '2026-11-25T18:00:00-07:00',
  geometry: '_p~iF~ps|U_ulLnnqC_mqNvxq`@',
  summary: {
    miles_by_level: { low: 0, moderate: 0, high: 100, severe: 0, no_travel: 0 },
    unknown_mi: 0,
    avg_risk: 2,
    unknown_checkpoints: 0,
    no_travel_stretches: [],
  },
  checkpoints: [
    { index: 0, lat: 38.5, lon: -120.2, mile: 0, eta: '2026-11-25T23:00:00Z', wind_mph: 5, gust_mph: 8, rain_in_hr: 0, snow_in_hr: 0, level: 'low', driver: 'wind' },
    { index: 1, lat: 43.252, lon: -126.453, mile: 100, eta: '2026-11-26T01:00:00Z', wind_mph: 40, gust_mph: 50, rain_in_hr: 0.1, snow_in_hr: 0, level: 'high', driver: 'wind' },
  ],
  segments: [{ start_mi: 0, end_mi: 100, geometry: '_p~iF~ps|U_ulLnnqC_mqNvxq`@', level: 'high' }],
};

export const recommendedRoute: Route = {
  ...testRoute,
  id: 'r2',
  name: 'Route B',
  rank: 1,
  reason: 'Fewest High miles (0 vs 100 on Route A).',
  duration_s: 7800,
  summary: {
    ...testRoute.summary,
    miles_by_level: { low: 100, moderate: 0, high: 0, severe: 0, no_travel: 0 },
    avg_risk: 0,
  },
  checkpoints: testRoute.checkpoints.map((point) => ({ ...point, level: 'low', wind_mph: 5, gust_mph: 8 })),
  segments: testRoute.segments.map((segment) => ({ ...segment, level: 'low' })),
};

export const testPlan: PlanResponse = {
  recommended_route_id: 'r2',
  no_safe_route: false,
  routes: [recommendedRoute, testRoute],
  corridor: { bbox: [-127, 38, -120, 44], max_grid_points: 150 },
};

export const testHeatmap: HeatmapResponse = {
  grid: { lats: [40, 40.3], lons: [-122, -122], spacing_deg: 0.3 },
  hours: 49,
  risk: Array.from({ length: 49 }, () => [0, 2]),
  wind: Array.from({ length: 49 }, () => [5, 38]),
  rain: Array.from({ length: 49 }, () => [0, 0]),
  snow: Array.from({ length: 49 }, () => [0, 0]),
};
