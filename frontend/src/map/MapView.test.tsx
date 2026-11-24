import { render } from '@testing-library/react';
import * as maplibregl from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { MapView } from './MapView';

describe('MapView', () => {
  it('shows every required provider attribution, uncollapsed', () => {
    const addControl = vi.spyOn(maplibregl.Map.prototype, 'addControl');
    render(<MapView />);

    const attribution = addControl.mock.calls
      .map(([control]) => control)
      .find((control) => control instanceof maplibregl.AttributionControl) as unknown as {
      options: { compact: boolean; customAttribution: string[] };
    };
    expect(attribution.options.compact).toBe(false);
    const text = attribution.options.customAttribution.join(' ');
    for (const name of ['OpenStreetMap contributors', 'OpenFreeMap', 'TomTom', 'Weather data by Open-Meteo.com']) {
      expect(text).toContain(name);
    }
  });

  it('removes the map on unmount', () => {
    const remove = vi.spyOn(maplibregl.Map.prototype, 'remove');
    render(<MapView />).unmount();
    expect(remove).toHaveBeenCalledOnce();
  });
});
