import type * as maplibregl from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { toFrames } from '../lib/heatmap';
import { recommendedRoute, testRoute } from '../test/fixtures';
import { HeatmapController } from './heatmapLayer';

const frames = toFrames({
  grid: { lats: [40, 40.3], lons: [-100, -100], spacing_deg: 0.3 },
  hours: 49,
  risk: Array.from({ length: 49 }, () => [0, 1]),
  wind: Array.from({ length: 49 }, () => [5, 30]),
  rain: Array.from({ length: 49 }, () => [0, 0]),
  snow: Array.from({ length: 49 }, () => [0, 0]),
});
// testRoute departs 23:00Z and arrives 01:00Z.
const START = '2026-11-25T23:00:00Z';

function fakeMap() {
  type FakeSource = Record<'setData' | 'setCoordinates' | 'play' | 'pause', ReturnType<typeof vi.fn>>;
  const sources = new Map<string, FakeSource>();
  const layers: { id: string; beforeId?: string }[] = [];
  const renderListeners: (() => void)[] = [];
  const map = {
    addSource: vi.fn<(id: string, spec?: unknown) => void>((id) => {
      sources.set(id, { setData: vi.fn(), setCoordinates: vi.fn(), play: vi.fn(), pause: vi.fn() });
    }),
    getSource: vi.fn((id: string) => sources.get(id)),
    addLayer: vi.fn((layer: { id: string }, beforeId?: string) => { layers.push({ id: layer.id, beforeId }); }),
    getLayer: vi.fn((id: string) => (id === 'trip-route-casing' || layers.some((l) => l.id === id) ? {} : undefined)),
    setLayoutProperty: vi.fn(),
    once: vi.fn((_event: string, listener: () => void) => { renderListeners.push(listener); }),
    triggerRepaint: vi.fn(),
  };
  const render = () => renderListeners.splice(0).forEach((listener) => listener());
  return { map, sources, layers, render, asMap: map as unknown as maplibregl.Map };
}

function truckFeatures(source: { setData: ReturnType<typeof vi.fn> } | undefined) {
  const calls = source?.setData.mock.calls ?? [];
  return (calls[calls.length - 1]?.[0] as GeoJSON.FeatureCollection<GeoJSON.Point>).features;
}

describe('HeatmapController', () => {
  it('adds one canvas source and raster layer beneath the routes when frames arrive', () => {
    const { map, layers, asMap } = fakeMap();
    const controller = new HeatmapController();
    controller.attach(asMap);
    controller.setData(frames, [testRoute], START, 'r1');
    const canvasCall = map.addSource.mock.calls.find(([id]) => id === 'heatmap-frames');
    expect(canvasCall?.[1]).toMatchObject({ type: 'canvas', animate: false });
    expect(layers.find((l) => l.id === 'heatmap-raster')?.beforeId).toBe('trip-route-casing');
  });

  it('moves through hours by repainting the canvas and markers, never re-creating sources', () => {
    const { map, sources, render, asMap } = fakeMap();
    const controller = new HeatmapController();
    controller.attach(asMap);
    controller.setData(frames, [testRoute, recommendedRoute], START, 'r2');
    const added = map.addSource.mock.calls.length;
    for (const hour of [0, 1, 2, 48]) controller.show(hour, 'risk');
    expect(map.addSource).toHaveBeenCalledTimes(added);
    const canvas = sources.get('heatmap-frames');
    expect(canvas?.play).toHaveBeenCalled();
    render();
    expect(canvas?.pause).toHaveBeenCalled();
  });

  it('places a truck marker for each route at the selected hour', () => {
    const { sources, asMap } = fakeMap();
    const controller = new HeatmapController();
    controller.attach(asMap);
    controller.setData(frames, [testRoute, recommendedRoute], START, 'r2');
    controller.show(1, 'risk');
    const features = truckFeatures(sources.get('heatmap-trucks'));
    expect(features).toHaveLength(2);
    const selected = features.find((f) => f.properties?.routeId === 'r2');
    expect(selected?.properties).toMatchObject({ selected: true, status: 'driving' });
    expect(selected?.geometry.coordinates[1]).toBeCloseTo((38.5 + 43.252) / 2);
    controller.show(48, 'risk');
    expect(truckFeatures(sources.get('heatmap-trucks'))[0]?.properties?.status).toBe('arrived');
  });

  it('reuses the canvas source for a new plan and hides the layer while frames are absent', () => {
    const { map, sources, asMap } = fakeMap();
    const controller = new HeatmapController();
    controller.attach(asMap);
    controller.setData(frames, [testRoute], START, 'r1');
    controller.setData(null, [], null, null);
    expect(map.setLayoutProperty).toHaveBeenLastCalledWith('heatmap-raster', 'visibility', 'none');
    expect(truckFeatures(sources.get('heatmap-trucks'))).toEqual([]);
    controller.setData(frames, [testRoute], START, 'r1');
    expect(map.addSource.mock.calls.filter(([id]) => id === 'heatmap-frames')).toHaveLength(1);
    expect(sources.get('heatmap-frames')?.setCoordinates).toHaveBeenCalled();
    expect(map.setLayoutProperty).toHaveBeenLastCalledWith('heatmap-raster', 'visibility', 'visible');
  });

  it('remembers data set before the map is ready', () => {
    const { map, asMap } = fakeMap();
    const controller = new HeatmapController();
    controller.setData(frames, [testRoute], START, 'r1');
    controller.show(5, 'wind');
    controller.attach(asMap);
    expect(map.addSource.mock.calls.map(([id]) => id)).toContain('heatmap-frames');
  });
});
