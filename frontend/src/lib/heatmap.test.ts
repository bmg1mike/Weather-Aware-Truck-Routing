import { describe, expect, it } from 'vitest';

import type { HeatmapResponse } from '../api/types';
import { testRoute } from '../test/fixtures';
import { paintFrame, positionAt, rasterLayout, toFrames } from './heatmap';
import { RISK_STYLES } from './risk';

// A 2 x 3 lattice at 0.5 degree with one corner missing (outside the corridor).
const response: HeatmapResponse = {
  grid: {
    lats: [40, 40, 40, 40.5, 40.5],
    lons: [-100, -99.5, -99, -100, -99.5],
    spacing_deg: 0.5,
  },
  hours: 2,
  risk: [[0, 1, null, 3, 4], [4, 4, 4, 4, 4]],
  wind: [[5, 30, null, 50, 60], [70, 70, 70, 70, 70]],
  rain: [[0, 0.1, null, 0.6, 1.2], [0, 0, 0, 0, 0]],
  snow: [[0, 0, null, 0, 0], [0, 0, 0, 0, 0]],
};

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

describe('toFrames', () => {
  it('flattens frames hour-major into typed arrays, with sentinels for missing forecasts', () => {
    const frames = toFrames(response);
    expect(frames).toMatchObject({ hours: 2, count: 5, spacing: 0.5 });
    expect(frames.risk).toBeInstanceOf(Int8Array);
    expect(Array.from(frames.risk)).toEqual([0, 1, -1, 3, 4, 4, 4, 4, 4, 4]);
    expect(frames.wind).toBeInstanceOf(Float32Array);
    expect(Number.isNaN(frames.wind[2])).toBe(true);
    expect(frames.rain[3]).toBeCloseTo(0.6);
  });
});

describe('rasterLayout', () => {
  it('covers the lattice with half-cell padding and maps pixels back to grid points', () => {
    const layout = rasterLayout(toFrames(response), 1);
    expect([layout.width, layout.height]).toEqual([3, 2]);
    expect(layout.coordinates).toEqual([
      [-100.25, 40.75], [-98.75, 40.75], [-98.75, 39.75], [-100.25, 39.75],
    ]);
    // Row 0 is the northern row (lat 40.5); the missing north-east corner has no point.
    expect(Array.from(layout.pixelIndex)).toEqual([3, 4, -1, 0, 1, 2]);
  });

  it('spaces canvas rows evenly in Web Mercator so latitude bands land where the map draws them', () => {
    const tall: HeatmapResponse = {
      ...response,
      grid: { lats: [20, 60], lons: [-100, -100], spacing_deg: 40 },
      risk: [[0, 4]], wind: [[0, 0]], rain: [[0, 0]], snow: [[0, 0]], hours: 1,
    };
    const layout = rasterLayout(toFrames(tall), 50);
    const column = Array.from({ length: layout.height }, (_, y) => layout.pixelIndex[y * layout.width]);
    const northRows = column.filter((i) => i === 1).length;
    // Mercator stretches high latitudes, so the 60N cell takes more than half of the rows.
    expect(northRows).toBeGreaterThan(layout.height / 2);
  });
});

describe('paintFrame', () => {
  const frames = toFrames(response);
  const layout = rasterLayout(frames, 1);
  const pixels = new Uint8ClampedArray(layout.width * layout.height * 4);
  const pixel = (i: number) => Array.from(pixels.slice(i * 4, i * 4 + 4));

  it('paints risk with the shared palette and leaves cells outside the corridor transparent', () => {
    paintFrame(pixels, layout, frames, 'risk', 0);
    expect(pixel(0).slice(0, 3)).toEqual(hexToRgb(RISK_STYLES.severe.colour)); // point 3
    expect(pixel(3).slice(0, 3)).toEqual(hexToRgb(RISK_STYLES.low.colour)); // point 0
    expect(pixel(2)[3]).toBe(0); // no grid point
  });

  it('paints missing forecasts as the no-forecast colour, not as Low', () => {
    paintFrame(pixels, layout, frames, 'risk', 0);
    expect(pixel(5).slice(0, 3)).toEqual(hexToRgb(RISK_STYLES.unknown.colour)); // point 2
    expect(pixel(5)[3]).toBeGreaterThan(0);
  });

  it('switches frames by hour without new data', () => {
    paintFrame(pixels, layout, frames, 'risk', 1);
    expect(pixel(3).slice(0, 3)).toEqual(hexToRgb(RISK_STYLES.no_travel.colour));
  });

  it('paints raw-value layers on a continuous scale where calm is transparent', () => {
    paintFrame(pixels, layout, frames, 'rain', 0);
    expect(pixel(3)[3]).toBe(0); // 0 in/hr
    const light = pixel(4)[3] ?? 0; // 0.1 in/hr
    const heavy = pixel(1)[3] ?? 0; // 1.2 in/hr
    expect(light).toBeGreaterThan(0);
    expect(heavy).toBeGreaterThan(light);
    expect(pixel(5)[3]).toBe(0); // missing raw value draws nothing
  });
});

describe('positionAt', () => {
  // testRoute runs from (38.5, -120.2) at 23:00Z to (43.252, -126.453) at 01:00Z.
  it('interpolates along checkpoints by ETA', () => {
    const halfway = positionAt(testRoute, new Date('2026-11-26T00:00:00Z'));
    expect(halfway.status).toBe('driving');
    expect(halfway.lat).toBeCloseTo((38.5 + 43.252) / 2);
    expect(halfway.lon).toBeCloseTo((-120.2 - 126.453) / 2);
  });

  it('waits at the origin before departure and stays at the destination after arrival', () => {
    expect(positionAt(testRoute, new Date('2026-11-25T20:00:00Z'))).toEqual({ lat: 38.5, lon: -120.2, status: 'before' });
    expect(positionAt(testRoute, new Date('2026-11-27T00:00:00Z'))).toEqual({ lat: 43.252, lon: -126.453, status: 'arrived' });
  });
});
