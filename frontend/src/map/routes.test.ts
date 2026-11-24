import { describe, expect, it } from 'vitest';

import type { Route } from '../api/types';
import { RISK_STYLES } from '../lib/risk';
import { checkpointFeatures, routeFeatures } from './routes';

const route: Route = {
  id: 'r1',
  rank: 1,
  reason: 'Fewest Severe miles.',
  distance_mi: 100,
  duration_s: 7200,
  arrival: '2026-11-25T18:00:00Z',
  geometry: '_p~iF~ps|U_ulLnnqC_mqNvxq`@',
  summary: { miles_by_level: { low: 0, moderate: 0, high: 0, severe: 0, no_travel: 0 }, unknown_mi: 100, avg_risk: null, unknown_checkpoints: 1 },
  checkpoints: [{ index: 0, lat: 38.5, lon: -120.2, mile: 0, eta: '2026-11-25T16:00:00Z', wind_mph: null, gust_mph: null, rain_in_hr: null, snow_in_hr: null, level: 'unknown', driver: null }],
};

describe('map route features', () => {
  it('decodes API polylines in longitude-latitude order and draws the selected route last', () => {
    const collection = routeFeatures([route, { ...route, id: 'r2' }], 'r1');
    expect(collection.features.map((feature) => feature.properties?.routeId)).toEqual(['r2', 'r1']);
    expect(collection.features[1]?.geometry.coordinates).toEqual([
      [-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252],
    ]);
  });

  it('shows only selected-route checkpoints and preserves unknown forecast presentation', () => {
    const collection = checkpointFeatures([route, { ...route, id: 'r2' }], 'r1');
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0]).toMatchObject({
      geometry: { type: 'Point', coordinates: [-120.2, 38.5] },
      properties: { colour: RISK_STYLES.unknown.colour, label: 'No forecast' },
    });
    expect(checkpointFeatures([route], 'missing').features).toEqual([]);
  });
});
