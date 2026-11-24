import * as maplibregl from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';

import type { Route } from '../api/types';
import { BASEMAP_STYLE_URL, INITIAL_VIEW, REQUIRED_ATTRIBUTION } from './attribution';
import { checkpointFeatures, routeFeatures } from './routes';

const EMPTY_ROUTES: Route[] = [];

maplibregl.setWorkerUrl(mapWorkerUrl);

function updateRoutes(map: maplibregl.Map, routes: Route[], selectedId: string | null, fit: boolean) {
  const lines = routeFeatures(routes, selectedId);
  map.getSource<maplibregl.GeoJSONSource>('trip-routes')?.setData(lines);
  map.getSource<maplibregl.GeoJSONSource>('trip-checkpoints')?.setData(checkpointFeatures(routes, selectedId));
  if (fit && lines.features.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    for (const feature of lines.features) {
      for (const coordinate of feature.geometry.coordinates) {
        const [lon, lat] = coordinate;
        if (lon !== undefined && lat !== undefined) bounds.extend([lon, lat]);
      }
    }
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: { top: 100, bottom: 220, left: 60, right: 60 }, maxZoom: 11 });
  }
}

export function MapView({
  routes = EMPTY_ROUTES,
  selectedId = null,
  onSelect,
}: {
  routes?: Route[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  const dataRef = useRef({ routes, selectedId, onSelect });
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    const changed = dataRef.current.routes !== routes;
    dataRef.current = { routes, selectedId, onSelect };
    if (mapRef.current && readyRef.current) updateRoutes(mapRef.current, routes, selectedId, changed);
  }, [routes, selectedId, onSelect]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: BASEMAP_STYLE_URL,
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        attributionControl: false,
      });
    } catch (error) {
      // WebGL may be unavailable even when the rest of the planner is usable.
      queueMicrotask(() => setMapError(error instanceof Error ? `Map unavailable: ${error.message}` : 'The map could not start. Check that WebGL is enabled in your browser.'));
      return;
    }
    map.addControl(
      new maplibregl.AttributionControl({ compact: false, customAttribution: [...REQUIRED_ATTRIBUTION] }),
    );
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('error', () => setMapError('Some map tiles could not load. Check your connection. Your trip details are still available.'));
    map.on('load', () => {
      setMapError(null);
      readyRef.current = true;
      map.addSource('trip-routes', { type: 'geojson', data: routeFeatures([], null) });
      map.addSource('trip-checkpoints', { type: 'geojson', data: checkpointFeatures([], null) });
      map.addLayer({
        id: 'trip-route-casing',
        type: 'line',
        source: 'trip-routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 },
      });
      map.addLayer({
        id: 'trip-route-lines',
        type: 'line',
        source: 'trip-routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['case', ['get', 'selected'], '#465735', '#8e9690'],
          'line-width': ['case', ['get', 'selected'], 5, 3],
          'line-opacity': ['case', ['get', 'selected'], 1, 0.6],
        },
      });
      map.addLayer({
        id: 'trip-checkpoint-dots',
        type: 'circle',
        source: 'trip-checkpoints',
        paint: { 'circle-radius': 5, 'circle-color': ['get', 'colour'], 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' },
      });
      map.on('click', 'trip-route-lines', (event) => {
        const id: unknown = event.features?.[0]?.properties?.routeId;
        if (typeof id === 'string') dataRef.current.onSelect?.(id);
      });
      map.on('mouseenter', 'trip-route-lines', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'trip-route-lines', () => { map.getCanvas().style.cursor = ''; });
      updateRoutes(map, dataRef.current.routes, dataRef.current.selectedId, true);
    });
    mapRef.current = map;
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(containerRef.current);
    return () => {
      resizeObserver.disconnect();
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <>
      <div ref={containerRef} className="map" role="region" aria-label="Route map" />
      {mapError && <p className="map-error" role="alert">{mapError}</p>}
    </>
  );
}
