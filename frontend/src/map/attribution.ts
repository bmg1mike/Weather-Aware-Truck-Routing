/** Attribution required by the data and tile providers (spec section 5). Always visible. */
export const REQUIRED_ATTRIBUTION: readonly string[] = [
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>',
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a>',
  '<a href="https://www.tomtom.com" target="_blank" rel="noopener">© TomTom</a>',
  '<a href="https://open-meteo.com" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a>',
];

export const BASEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';

/** Continental US, used before a trip is planned. */
export const INITIAL_VIEW = { center: [-98.5, 39.5] as [number, number], zoom: 3.6 };
