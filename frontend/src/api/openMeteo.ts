import { ApiError } from './client';
import type { SuppliedForecast, WeatherRequest } from './types';

/**
 * Fallback only: free hosting shares outbound IP addresses, so Open-Meteo can rate-limit the
 * server while the visitor's own address is fine. The backend then names the cells it needs and
 * this fetches them with the same parameters it would have used. Risk is still classified on the
 * server, and Open-Meteo needs no key, so nothing secret is in the bundle.
 */
const FORECAST_URL = 'https://api.open-meteo.com/v1/forecast';
const MAX_COORDS_PER_REQUEST = 100;
const HOURLY_VARIABLES = 'wind_speed_10m,wind_gusts_10m,rain,showers,snowfall';

async function fetchBatch(
  cells: [number, number][],
  request: WeatherRequest,
  signal?: AbortSignal,
): Promise<SuppliedForecast[]> {
  const params = new URLSearchParams({
    latitude: cells.map(([lat]) => lat).join(','),
    longitude: cells.map(([, lon]) => lon).join(','),
    hourly: HOURLY_VARIABLES,
    wind_speed_unit: 'mph',
    precipitation_unit: 'inch',
    timezone: 'GMT',
    start_hour: request.start_hour,
    end_hour: request.end_hour,
  });
  let response: Response;
  try {
    response = await fetch(`${FORECAST_URL}?${params}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_error', 'Could not reach Open-Meteo. Check your connection.');
  }
  if (response.status === 429) {
    throw new ApiError(503, 'provider_rate_limited', 'Open-Meteo is busy. Please try again later.');
  }
  const body: unknown = response.ok ? await response.json().catch(() => null) : null;
  const locations = Array.isArray(body) ? body : body ? [body] : [];
  if (locations.length !== cells.length) {
    throw new ApiError(502, 'provider_unavailable', 'Open-Meteo sent an unexpected response.');
  }
  return cells.map(([lat, lon], i) => ({
    lat,
    lon,
    hourly: (locations[i] as { hourly?: SuppliedForecast['hourly'] }).hourly ?? {},
  }));
}

export async function fetchForecasts(
  request: WeatherRequest,
  signal?: AbortSignal,
): Promise<SuppliedForecast[]> {
  const batches: [number, number][][] = [];
  for (let i = 0; i < request.cells.length; i += MAX_COORDS_PER_REQUEST) {
    batches.push(request.cells.slice(i, i + MAX_COORDS_PER_REQUEST));
  }
  const results = await Promise.all(batches.map((batch) => fetchBatch(batch, request, signal)));
  return results.flat();
}
