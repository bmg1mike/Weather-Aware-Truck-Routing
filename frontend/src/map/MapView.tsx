import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef } from 'react';

import { BASEMAP_STYLE_URL, INITIAL_VIEW, REQUIRED_ATTRIBUTION } from './attribution';

/**
 * The map is created exactly once. Later phases add route, checkpoint and heatmap sources and
 * update them with `setData`, never by re-creating the map or its sources.
 */
export function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE_URL,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
      attributionControl: false,
    });
    map.addControl(
      new maplibregl.AttributionControl({ compact: false, customAttribution: [...REQUIRED_ATTRIBUTION] }),
    );
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="map" role="region" aria-label="Route map" />;
}
