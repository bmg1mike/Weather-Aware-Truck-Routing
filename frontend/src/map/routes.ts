import type { FeatureCollection, LineString, Point } from 'geojson';

import type { Route } from '../api/types';
import { RISK_STYLES } from '../lib/risk';

function decodePolyline(encoded: string): [number, number][] {
  const coordinates: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lon = 0;
  while (index < encoded.length) {
    const values: number[] = [];
    for (let axis = 0; axis < 2; axis += 1) {
      let result = 0;
      let shift = 0;
      let byte: number;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index < encoded.length);
      values.push(result & 1 ? ~(result >> 1) : result >> 1);
    }
    lat += values[0] ?? 0;
    lon += values[1] ?? 0;
    coordinates.push([lon / 1e5, lat / 1e5]);
  }
  return coordinates;
}

export function routeFeatures(routes: Route[], selectedId: string | null): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: [...routes]
      .sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId))
      .map((route) => ({
        type: 'Feature',
        properties: { routeId: route.id, selected: route.id === selectedId },
        geometry: { type: 'LineString', coordinates: decodePolyline(route.geometry) },
      })),
  };
}

export function segmentFeatures(routes: Route[], selectedId: string | null): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: [...routes]
      .sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId))
      .flatMap((route) => route.segments.map((segment) => ({
        type: 'Feature',
        properties: {
          routeId: route.id,
          selected: route.id === selectedId,
          colour: RISK_STYLES[segment.level].colour,
          level: segment.level,
        },
        geometry: { type: 'LineString', coordinates: decodePolyline(segment.geometry) },
      }))),
  };
}

export function checkpointFeatures(routes: Route[], selectedId: string | null): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [...routes].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId)).flatMap((route) =>
      route.checkpoints.map((checkpoint) => ({
        type: 'Feature',
        properties: {
          routeId: route.id,
          index: checkpoint.index,
          selected: route.id === selectedId,
          colour: RISK_STYLES[checkpoint.level].colour,
          label: RISK_STYLES[checkpoint.level].label,
          mile: checkpoint.mile,
        },
        geometry: { type: 'Point', coordinates: [checkpoint.lon, checkpoint.lat] },
      })),
    ),
  };
}
