import { describe, expect, it } from 'vitest';

import { RISK_STYLES } from '../lib/risk';
import { testRoute } from '../test/fixtures';
import { checkpointFeatures, routeFeatures, segmentFeatures } from './routes';

describe('map route features', () => {
  it('decodes API polylines in longitude-latitude order and draws the selected route last', () => {
    const collection = routeFeatures([testRoute, { ...testRoute, id: 'r2' }], 'r1');
    expect(collection.features.map((feature) => feature.properties?.routeId)).toEqual(['r2', 'r1']);
    expect(collection.features[1]?.geometry.coordinates).toEqual([
      [-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252],
    ]);
  });

  it('uses the server segment risk, even if checkpoint weather would suggest another level', () => {
    const collection = segmentFeatures([{
      ...testRoute,
      segments: [{ ...testRoute.segments[0]!, level: 'severe' }],
    }], 'r1');
    expect(collection.features[0]).toMatchObject({
      properties: { routeId: 'r1', selected: true, colour: RISK_STYLES.severe.colour, level: 'severe' },
      geometry: { type: 'LineString', coordinates: [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]] },
    });
  });

  it('keeps checkpoints on all routes, dims alternatives and preserves unknown data', () => {
    const unknown = { ...testRoute, checkpoints: [{ ...testRoute.checkpoints[0]!, level: 'unknown' as const }] };
    const collection = checkpointFeatures([unknown, { ...testRoute, id: 'r2' }], 'r1');
    expect(collection.features).toHaveLength(3);
    expect(collection.features[0]?.properties).toMatchObject({ routeId: 'r2', selected: false });
    expect(collection.features[2]).toMatchObject({
      geometry: { type: 'Point', coordinates: [-120.2, 38.5] },
      properties: { routeId: 'r1', index: 0, selected: true, colour: RISK_STYLES.unknown.colour, label: 'No forecast' },
    });
  });
});
