import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// MapLibre needs WebGL, which jsdom lacks. Tests assert on our wiring, not on rendering tiles.
vi.mock('maplibre-gl', () => {
  // Methods live on the prototype so tests can spy on them.
  class FakeMap {
    addControl() {
      return this;
    }
    remove() {}
  }
  class FakeControl {
    constructor(public options?: unknown) {}
  }
  return { Map: FakeMap, AttributionControl: FakeControl, NavigationControl: FakeControl };
});
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
