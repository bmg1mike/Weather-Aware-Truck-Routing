/**
 * Heatmap frames in memory and their raster presentation (spec section 7).
 *
 * The backend sends all 49 frames once; they are flattened into typed arrays here so moving the
 * slider is an array lookup, never a network call. Risk levels arrive already classified: this
 * module only maps them to the shared palette. Wind, rain and snow layers show raw forecast values
 * on a continuous display scale that deliberately does not mirror the risk thresholds.
 */
import type { HeatmapResponse, Route } from '../api/types';
import { RISK_LEVELS, RISK_STYLES } from './risk';

export type HeatmapLayerKey = 'risk' | 'wind' | 'rain' | 'snow';

export interface HeatmapFrames {
  hours: number;
  count: number;
  spacing: number;
  lats: Float64Array;
  lons: Float64Array;
  /** hours × count, hour-major. -1 means no forecast. */
  risk: Int8Array;
  /** hours × count, hour-major. NaN means no forecast. */
  wind: Float32Array;
  rain: Float32Array;
  snow: Float32Array;
}

export const NO_FORECAST = -1;

export function toFrames(response: HeatmapResponse): HeatmapFrames {
  const count = response.grid.lats.length;
  const hours = response.hours;
  const risk = new Int8Array(hours * count);
  const flat = (series: (number | null)[][]) => {
    const out = new Float32Array(hours * count);
    series.forEach((frame, h) => frame.forEach((v, i) => { out[h * count + i] = v ?? Number.NaN; }));
    return out;
  };
  response.risk.forEach((frame, h) => frame.forEach((v, i) => { risk[h * count + i] = v ?? NO_FORECAST; }));
  return {
    hours,
    count,
    spacing: response.grid.spacing_deg,
    lats: Float64Array.from(response.grid.lats),
    lons: Float64Array.from(response.grid.lons),
    risk,
    wind: flat(response.wind),
    rain: flat(response.rain),
    snow: flat(response.snow),
  };
}

// --- raster layout -------------------------------------------------------------------------------

export type Corners = [[number, number], [number, number], [number, number], [number, number]];

export interface RasterLayout {
  width: number;
  height: number;
  /** Top-left, top-right, bottom-right, bottom-left as [lon, lat], for a MapLibre canvas source. */
  coordinates: Corners;
  /** Grid point drawn at each canvas pixel (row-major from the north-west), or -1 for none. */
  pixelIndex: Int32Array;
}

const mercatorY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const inverseMercatorY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90;

/**
 * One canvas column per lattice column. Rows are spaced evenly in Web Mercator (``rowsPerCell``
 * canvas rows per lattice row) because MapLibre stretches the image linearly in projected space.
 */
export function rasterLayout(frames: HeatmapFrames, rowsPerCell = 4): RasterLayout {
  const s = frames.spacing;
  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
  for (let i = 0; i < frames.count; i += 1) {
    minLat = Math.min(minLat, frames.lats[i] ?? 0); maxLat = Math.max(maxLat, frames.lats[i] ?? 0);
    minLon = Math.min(minLon, frames.lons[i] ?? 0); maxLon = Math.max(maxLon, frames.lons[i] ?? 0);
  }
  if (frames.count === 0) { minLat = maxLat = minLon = maxLon = 0; }
  const cols = Math.round((maxLon - minLon) / s) + 1;
  const rows = Math.round((maxLat - minLat) / s) + 1;
  const west = minLon - s / 2, east = maxLon + s / 2, south = minLat - s / 2, north = maxLat + s / 2;

  const cellPoint = new Int32Array(rows * cols).fill(-1);
  for (let i = 0; i < frames.count; i += 1) {
    const row = Math.round(((frames.lats[i] ?? 0) - minLat) / s);
    const col = Math.round(((frames.lons[i] ?? 0) - minLon) / s);
    cellPoint[row * cols + col] = i;
  }

  const height = rows * rowsPerCell;
  const top = mercatorY(north), bottom = mercatorY(south);
  const pixelIndex = new Int32Array(cols * height).fill(-1);
  for (let y = 0; y < height; y += 1) {
    const lat = inverseMercatorY(top + ((y + 0.5) / height) * (bottom - top));
    const row = Math.round((lat - minLat) / s);
    if (row < 0 || row >= rows) continue;
    for (let col = 0; col < cols; col += 1) pixelIndex[y * cols + col] = cellPoint[row * cols + col] ?? -1;
  }
  return {
    width: cols,
    height,
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
    pixelIndex,
  };
}

// --- painting ------------------------------------------------------------------------------------

type Rgb = [number, number, number];

function hexToRgb(hex: string): Rgb {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const RISK_RGB: Rgb[] = RISK_LEVELS.map((level) => hexToRgb(RISK_STYLES[level].colour));
const UNKNOWN_RGB = hexToRgb(RISK_STYLES.unknown.colour);
const RISK_ALPHA = 255;
const UNKNOWN_ALPHA = 120;

export interface ValueScale {
  label: string;
  unit: string;
  max: number;
  stops: Rgb[];
}

/** Display scales for raw values. Purely visual: they are not risk thresholds. */
export const VALUE_SCALES: Record<Exclude<HeatmapLayerKey, 'risk'>, ValueScale> = {
  wind: { label: 'Wind', unit: 'mph', max: 60, stops: [[204, 236, 230], [65, 174, 168], [14, 84, 110]] },
  rain: { label: 'Rain', unit: 'in/hr', max: 1, stops: [[198, 219, 239], [66, 146, 198], [8, 48, 107]] },
  snow: { label: 'Snow', unit: 'in/hr', max: 3, stops: [[218, 218, 235], [158, 154, 200], [84, 39, 143]] },
};

function rampColour(stops: Rgb[], t: number): Rgb {
  const scaled = t * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const f = scaled - i;
  const a = stops[i] ?? [0, 0, 0], b = stops[i + 1] ?? a;
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** Writes one frame of one layer as RGBA into ``target`` (length width × height × 4). */
export function paintFrame(
  target: Uint8ClampedArray,
  layout: RasterLayout,
  frames: HeatmapFrames,
  layer: HeatmapLayerKey,
  hour: number,
): void {
  const offset = hour * frames.count;
  const values = layer === 'risk' ? null : frames[layer];
  const scale = layer === 'risk' ? null : VALUE_SCALES[layer];
  for (let p = 0; p < layout.pixelIndex.length; p += 1) {
    const point = layout.pixelIndex[p] ?? -1;
    const o = p * 4;
    let rgb: Rgb | null = null;
    let alpha = 0;
    if (point >= 0) {
      if (values === null || scale === null) {
        const level = frames.risk[offset + point] ?? NO_FORECAST;
        rgb = level === NO_FORECAST ? UNKNOWN_RGB : (RISK_RGB[level] ?? UNKNOWN_RGB);
        alpha = level === NO_FORECAST ? UNKNOWN_ALPHA : RISK_ALPHA;
      } else {
        const value = values[offset + point] ?? Number.NaN;
        if (Number.isFinite(value) && value > 0) {
          const t = Math.min(value / scale.max, 1);
          rgb = rampColour(scale.stops, t);
          alpha = 60 + 195 * t;
        }
      }
    }
    target[o] = rgb?.[0] ?? 0;
    target[o + 1] = rgb?.[1] ?? 0;
    target[o + 2] = rgb?.[2] ?? 0;
    target[o + 3] = alpha;
  }
}

// --- truck position ------------------------------------------------------------------------------

export interface TruckPosition {
  lat: number;
  lon: number;
  status: 'before' | 'driving' | 'arrived';
}

/** Where the truck would be at ``time``, interpolated between checkpoint ETAs. */
export function positionAt(route: Route, time: Date): TruckPosition {
  const points = route.checkpoints;
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return { lat: 0, lon: 0, status: 'before' };
  const t = time.getTime();
  if (t < Date.parse(first.eta)) return { lat: first.lat, lon: first.lon, status: 'before' };
  if (t >= Date.parse(last.eta)) return { lat: last.lat, lon: last.lon, status: 'arrived' };
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i]!, b = points[i + 1]!;
    const ta = Date.parse(a.eta), tb = Date.parse(b.eta);
    if (t >= ta && t < tb) {
      const f = tb > ta ? (t - ta) / (tb - ta) : 0;
      return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f, status: 'driving' };
    }
  }
  return { lat: last.lat, lon: last.lon, status: 'arrived' };
}
