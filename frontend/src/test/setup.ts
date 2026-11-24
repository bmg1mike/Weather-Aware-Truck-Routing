import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

// MapLibre needs WebGL, which jsdom lacks. Tests assert on our wiring, not on rendering tiles.
vi.mock('maplibre-gl', () => {
  // Methods live on the prototype so tests can spy on them.
  class FakeMap {
    sources = new Map<string, Record<'setData' | 'setCoordinates' | 'play' | 'pause', ReturnType<typeof vi.fn>>>();
    layers = new Set<string>();
    listeners = new Map<string, ((event: unknown) => void)[]>();
    canvas = document.createElement('canvas');
    constructor(public options: { container: HTMLElement }) {}
    addControl() {
      return this;
    }
    remove() {}
    on(event: string, layerOrListener: string | ((event: unknown) => void), listener?: (event: unknown) => void) {
      const callback = typeof layerOrListener === 'function' ? layerOrListener : listener;
      const key = typeof layerOrListener === 'string' ? `${event}:${layerOrListener}` : event;
      if (callback) {
        this.listeners.set(key, [...(this.listeners.get(key) ?? []), callback]);
        if (event === 'load') callback({ target: this });
      }
      return this;
    }
    fire(event: string, data: unknown = {}) {
      this.listeners.get(event)?.forEach((listener) => listener(data));
      return this;
    }
    addSource(id: string) { this.sources.set(id, { setData: vi.fn(), setCoordinates: vi.fn(), play: vi.fn(), pause: vi.fn() }); return this; }
    getSource(id: string) { return this.sources.get(id); }
    addLayer(layer: { id: string }) { this.layers.add(layer.id); return this; }
    getLayer(id: string) { return this.layers.has(id) ? { id } : undefined; }
    setLayoutProperty() { return this; }
    once() { return this; }
    fitBounds() { return this; }
    getContainer() { return this.options.container; }
    getCanvas() { return this.canvas; }
    queryRenderedFeatures() { return []; }
    resize() {}
  }
  class FakeBounds {
    points: unknown[] = [];
    extend(point: unknown) { this.points.push(point); return this; }
    isEmpty() { return this.points.length === 0; }
  }
  class FakePopup {
    element = document.createElement('div');
    close?: () => void;
    setLngLat() { return this; }
    setDOMContent(node: HTMLElement) { this.element.append(node); return this; }
    addTo(map: FakeMap) { map.getContainer().append(this.element); return this; }
    on(_event: string, listener: () => void) { this.close = listener; return this; }
    off() { this.close = undefined; return this; }
    remove() { this.element.remove(); this.close?.(); }
  }
  class FakeControl {
    constructor(public options?: unknown) {}
  }
  return { Map: FakeMap, AttributionControl: FakeControl, NavigationControl: FakeControl, LngLatBounds: FakeBounds, Popup: FakePopup, setWorkerUrl: vi.fn() };
});
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));

beforeEach(() => {
  // jsdom has no canvas backend; without this it logs "Not implemented" for every getContext.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
