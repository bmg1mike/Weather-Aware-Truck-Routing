import type { FeatureCollection, Point } from 'geojson';
import type * as maplibregl from 'maplibre-gl';

import type { Route } from '../api/types';
import type { HeatmapView } from '../components/HeatmapPanel';
import {
  type HeatmapFrames,
  type HeatmapLayerKey,
  paintFrame,
  positionAt,
  type RasterLayout,
  rasterLayout,
} from '../lib/heatmap';

const CANVAS_SOURCE = 'heatmap-frames';
const RASTER_LAYER = 'heatmap-raster';
const TRUCK_SOURCE = 'heatmap-trucks';
const TRUCK_LAYER = 'heatmap-truck-markers';
const BELOW_LAYER = 'trip-route-casing';
const HOUR_MS = 3_600_000;

type CanvasSource = maplibregl.CanvasSource;
type GeoJSONSource = maplibregl.GeoJSONSource;

const EMPTY_TRUCKS: FeatureCollection<Point> = { type: 'FeatureCollection', features: [] };

/**
 * Owns the heatmap's map objects. Frames live in memory; ``show`` repaints a small canvas (one
 * pixel per lattice cell, smoothed by MapLibre's linear resampling) and moves the truck markers.
 * Sources are created once and then updated in place: the slider never re-creates map state and
 * never touches the network.
 */
export class HeatmapController implements HeatmapView {
  private map: maplibregl.Map | null = null;
  private frames: HeatmapFrames | null = null;
  private layout: RasterLayout | null = null;
  private routes: Route[] = [];
  private startMs = 0;
  private selectedId: string | null = null;
  private hour = 0;
  private layer: HeatmapLayerKey = 'risk';
  private readonly canvas = document.createElement('canvas');
  private context: CanvasRenderingContext2D | null | undefined;
  private image: ImageData | null = null;

  attach(map: maplibregl.Map): void {
    this.map = map;
    if (!map.getSource(TRUCK_SOURCE)) {
      map.addSource(TRUCK_SOURCE, { type: 'geojson', data: EMPTY_TRUCKS });
      map.addLayer({
        id: TRUCK_LAYER,
        type: 'circle',
        source: TRUCK_SOURCE,
        paint: {
          'circle-radius': ['case', ['get', 'selected'], 7, 5],
          'circle-color': '#282e27',
          'circle-opacity': ['case', ['get', 'selected'], 1, 0.45],
          'circle-stroke-width': ['case', ['get', 'selected'], 3, 2],
          'circle-stroke-color': '#d7ed9b',
          'circle-stroke-opacity': ['case', ['get', 'selected'], 1, 0.45],
        },
      });
    }
    this.install();
    this.draw();
  }

  detach(): void {
    this.map = null;
  }

  setData(frames: HeatmapFrames | null, routes: Route[], start: string | null, selectedId: string | null): void {
    this.frames = frames;
    this.routes = routes;
    this.startMs = start ? Date.parse(start) : 0;
    this.selectedId = selectedId;
    this.layout = frames ? rasterLayout(frames) : null;
    this.image = null;
    if (this.layout) {
      this.canvas.width = this.layout.width;
      this.canvas.height = this.layout.height;
    }
    this.install();
    this.draw();
  }

  setSelected(selectedId: string | null): void {
    this.selectedId = selectedId;
    this.drawTrucks();
  }

  show(hour: number, layer: HeatmapLayerKey): void {
    this.hour = hour;
    this.layer = layer;
    this.draw();
  }

  private install(): void {
    const map = this.map;
    if (!map) return;
    const visible = this.layout !== null;
    if (this.layout) {
      const source = map.getSource<CanvasSource>(CANVAS_SOURCE);
      if (source) {
        source.setCoordinates(this.layout.coordinates);
      } else {
        map.addSource(CANVAS_SOURCE, {
          type: 'canvas',
          canvas: this.canvas,
          coordinates: this.layout.coordinates,
          animate: false,
        });
        map.addLayer(
          {
            id: RASTER_LAYER,
            type: 'raster',
            source: CANVAS_SOURCE,
            paint: { 'raster-opacity': 0.62, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
          },
          map.getLayer(BELOW_LAYER) ? BELOW_LAYER : undefined,
        );
      }
    }
    if (map.getLayer(RASTER_LAYER)) map.setLayoutProperty(RASTER_LAYER, 'visibility', visible ? 'visible' : 'none');
  }

  private draw(): void {
    this.drawFrame();
    this.drawTrucks();
  }

  private drawFrame(): void {
    const map = this.map;
    if (!map || !this.frames || !this.layout) return;
    if (this.context === undefined) this.context = this.canvas.getContext('2d');
    const context = this.context;
    if (context) {
      this.image ??= context.createImageData(this.layout.width, this.layout.height);
      paintFrame(this.image.data, this.layout, this.frames, this.layer, Math.min(this.hour, this.frames.hours - 1));
      context.putImageData(this.image, 0, 0);
    }
    // A non-animated canvas source uploads its texture only while playing: play for one render.
    const source = map.getSource<CanvasSource>(CANVAS_SOURCE);
    if (source) {
      source.play();
      map.once('render', () => source.pause());
    }
  }

  private drawTrucks(): void {
    const source = this.map?.getSource<GeoJSONSource>(TRUCK_SOURCE);
    if (!source) return;
    if (!this.frames) {
      source.setData(EMPTY_TRUCKS);
      return;
    }
    const time = new Date(this.startMs + this.hour * HOUR_MS);
    source.setData({
      type: 'FeatureCollection',
      features: [...this.routes]
        .sort((a, b) => Number(a.id === this.selectedId) - Number(b.id === this.selectedId))
        .map((route) => {
          const position = positionAt(route, time);
          return {
            type: 'Feature',
            properties: { routeId: route.id, selected: route.id === this.selectedId, status: position.status },
            geometry: { type: 'Point', coordinates: [position.lon, position.lat] },
          };
        }),
    });
  }
}
