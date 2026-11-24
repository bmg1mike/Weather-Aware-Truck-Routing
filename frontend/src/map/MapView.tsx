import * as maplibregl from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import type { Route } from '../api/types';
import { CheckpointDetails } from '../components/CheckpointDetails';
import { BASEMAP_STYLE_URL, INITIAL_VIEW, REQUIRED_ATTRIBUTION } from './attribution';
import { checkpointFeatures, routeFeatures, segmentFeatures } from './routes';

const EMPTY_ROUTES: Route[] = [];

maplibregl.setWorkerUrl(mapWorkerUrl);

function updateRoutes(map: maplibregl.Map, routes: Route[], selectedId: string | null, fit: boolean) {
  const lines = routeFeatures(routes, selectedId);
  map.getSource<maplibregl.GeoJSONSource>('trip-routes')?.setData(lines);
  map.getSource<maplibregl.GeoJSONSource>('trip-segments')?.setData(segmentFeatures(routes, selectedId));
  map.getSource<maplibregl.GeoJSONSource>('trip-checkpoints')?.setData(checkpointFeatures(routes, selectedId));
  if (fit && lines.features.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    for (const feature of lines.features) {
      for (const coordinate of feature.geometry.coordinates) {
        const [lon, lat] = coordinate;
        if (lon !== undefined && lat !== undefined) bounds.extend([lon, lat]);
      }
    }
    const narrow = map.getContainer().clientWidth < 500;
    if (!bounds.isEmpty()) map.fitBounds(bounds, {
      padding: { top: 100, bottom: 190, left: narrow ? 24 : 60, right: narrow ? 24 : 60 },
      maxZoom: 11,
      duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 700,
    });
  }
}

export function MapView({
  routes = EMPTY_ROUTES,
  selectedId = null,
  onSelect,
  checkpointIndex = null,
  onInspect,
}: {
  routes?: Route[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  checkpointIndex?: number | null;
  onInspect?: (routeId: string, index: number | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  const dataRef = useRef({ routes, selectedId, onSelect, onInspect });
  const [mapError, setMapError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [popupContainer] = useState(() => document.createElement('div'));
  const inspectedRoute = routes.find((route) => route.id === selectedId);
  const checkpoint = inspectedRoute?.checkpoints.find((point) => point.index === checkpointIndex);

  useEffect(() => {
    const changed = dataRef.current.routes !== routes;
    dataRef.current = { routes, selectedId, onSelect, onInspect };
    if (mapRef.current && readyRef.current) updateRoutes(mapRef.current, routes, selectedId, changed);
  }, [routes, selectedId, onSelect, onInspect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !inspectedRoute || !checkpoint) return;
    const popup = new maplibregl.Popup({ offset: 12, maxWidth: '300px', focusAfterOpen: false, closeOnClick: false })
      .setLngLat([checkpoint.lon, checkpoint.lat])
      .setDOMContent(popupContainer)
      .addTo(map);
    const close = () => dataRef.current.onInspect?.(inspectedRoute.id, null);
    popup.on('close', close);
    return () => {
      popup.off('close', close);
      popup.remove();
    };
  }, [ready, inspectedRoute, checkpoint, popupContainer]);

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
      map.addSource('trip-segments', { type: 'geojson', data: segmentFeatures([], null) });
      map.addSource('trip-checkpoints', { type: 'geojson', data: checkpointFeatures([], null) });
      map.addLayer({
        id: 'trip-route-casing',
        type: 'line',
        source: 'trip-routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#ffffff',
          'line-width': ['case', ['get', 'selected'], 9, 6],
          'line-opacity': ['case', ['get', 'selected'], 0.95, 0.35],
        },
      });
      map.addLayer({
        id: 'trip-route-lines',
        type: 'line',
        source: 'trip-segments',
        filter: ['!=', ['get', 'level'], 'unknown'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'colour'],
          'line-width': ['case', ['get', 'selected'], 5, 3],
          'line-opacity': ['case', ['get', 'selected'], 1, 0.35],
        },
      });
      map.addLayer({
        id: 'trip-unknown-lines',
        type: 'line',
        source: 'trip-segments',
        filter: ['==', ['get', 'level'], 'unknown'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'colour'],
          'line-width': ['case', ['get', 'selected'], 5, 3],
          'line-opacity': ['case', ['get', 'selected'], 1, 0.35],
          'line-dasharray': [2, 2],
        },
      });
      map.addLayer({
        id: 'trip-checkpoint-dots',
        type: 'circle',
        source: 'trip-checkpoints',
        paint: {
          'circle-radius': ['case', ['get', 'selected'], 5, 3],
          'circle-color': ['get', 'colour'],
          'circle-opacity': ['case', ['get', 'selected'], 1, 0.35],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-opacity': ['case', ['get', 'selected'], 1, 0.35],
        },
      });
      map.on('click', (event) => {
        const features = map.queryRenderedFeatures(event.point, { layers: ['trip-checkpoint-dots', 'trip-route-lines', 'trip-unknown-lines'] });
        const feature = features.find((item) => item.layer.id === 'trip-checkpoint-dots') ?? features[0];
        const id: unknown = feature?.properties?.routeId;
        const index: unknown = feature?.properties?.index;
        if (typeof id !== 'string') return;
        if (feature?.layer.id === 'trip-checkpoint-dots' && typeof index === 'number') {
          dataRef.current.onInspect?.(id, index);
        } else {
          dataRef.current.onSelect?.(id);
        }
      });
      for (const layer of ['trip-route-lines', 'trip-unknown-lines', 'trip-checkpoint-dots']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      }
      updateRoutes(map, dataRef.current.routes, dataRef.current.selectedId, true);
      setReady(true);
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
      {checkpoint && inspectedRoute && createPortal(<CheckpointDetails checkpoint={checkpoint} routeName={inspectedRoute.name} />, popupContainer)}
      {mapError && <p className="map-error" role="alert">{mapError}</p>}
    </>
  );
}
