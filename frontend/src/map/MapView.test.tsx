import { act, render, screen } from '@testing-library/react';
import * as maplibregl from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { MapView } from './MapView';
import { testPlan } from '../test/fixtures';

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

  it('updates existing sources on selection, fits the routes only once and keeps road geometry', () => {
    const addSource = vi.spyOn(maplibregl.Map.prototype, 'addSource');
    const addLayer = vi.spyOn(maplibregl.Map.prototype, 'addLayer');
    const fitBounds = vi.spyOn(maplibregl.Map.prototype, 'fitBounds');
    const getSource = vi.spyOn(maplibregl.Map.prototype, 'getSource');
    const { rerender } = render(<MapView routes={testPlan.routes} selectedId="r1" />);
    expect(addSource).toHaveBeenCalledTimes(3);
    expect(fitBounds).toHaveBeenCalledOnce();
    expect(addLayer.mock.calls.find(([layer]) => layer.id === 'trip-route-lines')?.[0]).toMatchObject({
      source: 'trip-segments',
      paint: { 'line-color': ['get', 'colour'] },
    });
    const segmentSource = getSource.mock.results.find((_, index) => getSource.mock.calls[index]?.[0] === 'trip-segments')?.value;
    const setData = vi.spyOn(segmentSource, 'setData');
    rerender(<MapView routes={testPlan.routes} selectedId="r2" />);
    expect(setData).toHaveBeenLastCalledWith(expect.objectContaining({
      features: expect.arrayContaining([expect.objectContaining({ properties: expect.objectContaining({ routeId: 'r2', selected: true }) })]),
    }));
    expect(addSource).toHaveBeenCalledTimes(3);
    expect(fitBounds).toHaveBeenCalledOnce();
  });

  it('selects routes from map clicks and opens the complete checkpoint popup', () => {
    const onSelect = vi.fn();
    const onInspect = vi.fn();
    const query = vi.spyOn(maplibregl.Map.prototype, 'queryRenderedFeatures');
    const on = vi.spyOn(maplibregl.Map.prototype, 'on');
    const { rerender } = render(<MapView routes={testPlan.routes} selectedId="r2" onSelect={onSelect} onInspect={onInspect} />);
    const map = on.mock.contexts[0];
    if (!(map instanceof maplibregl.Map)) throw new Error('Map was not created');
    const lineFeature: Partial<maplibregl.MapGeoJSONFeature> = { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { routeId: 'r1' }, layer: { id: 'trip-route-lines', type: 'line', source: 'trip-segments' }, source: 'trip-segments', state: {} };
    query.mockReturnValue([lineFeature as maplibregl.MapGeoJSONFeature]);
    act(() => { map.fire('click', { point: { x: 1, y: 1 } }); });
    expect(onSelect).toHaveBeenCalledWith('r1');
    const pointFeature: Partial<maplibregl.MapGeoJSONFeature> = { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { routeId: 'r1', index: 1 }, layer: { id: 'trip-checkpoint-dots', type: 'circle', source: 'trip-checkpoints' }, source: 'trip-checkpoints', state: {} };
    query.mockReturnValue([pointFeature as maplibregl.MapGeoJSONFeature]);
    act(() => { map.fire('click', { point: { x: 1, y: 1 } }); });
    expect(onInspect).toHaveBeenCalledWith('r1', 1);
    rerender(<MapView routes={testPlan.routes} selectedId="r1" checkpointIndex={1} onSelect={onSelect} onInspect={onInspect} />);
    const popup = screen.getByRole('region', { name: 'Route A, checkpoint 2 weather' });
    expect(popup).toHaveTextContent('High');
    expect(popup).toHaveTextContent('40.0 mph');
    expect(popup).toHaveTextContent('50.0 mph');
    expect(popup).toHaveTextContent('0.100 in/hr');
    expect(popup).toHaveTextContent('0.000 in/hr');
    expect(popup).toHaveTextContent('Risk driver Wind');
    expect(popup).toHaveTextContent('ETA');
  });
});
