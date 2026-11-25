import { fetchForecasts } from './openMeteo';
import type {
  ErrorResponse,
  GeocodeResponse,
  HeatmapRequest,
  HeatmapResponse,
  PlanRequest,
  PlanResponse,
  SuppliedForecast,
  WeatherRequest,
} from './types';

const RETRYABLE_STATUSES = new Set([0, 500, 502, 503, 504]);

/** Error thrown for any failed API call, carrying the backend's `{ error: { code, message } }`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterS: number | null;
  /** Set when Open-Meteo rate-limited the server: the forecasts the browser may fetch instead. */
  readonly weatherRequest: WeatherRequest | null;

  constructor(
    status: number,
    code: string,
    message: string,
    retryAfterS: number | null = null,
    weatherRequest: WeatherRequest | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterS = retryAfterS;
    this.weatherRequest = weatherRequest;
  }

  /** Network failures, provider timeouts and rate limits are worth a retry button. */
  get retryable(): boolean {
    return RETRYABLE_STATUSES.has(this.status);
  }
}

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

function isErrorResponse(body: unknown): body is ErrorResponse {
  const error = (body as Partial<ErrorResponse> | null)?.error;
  return typeof error?.code === 'string' && typeof error.message === 'string';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    });
  } catch (error) {
    // A cancelled request (e.g. superseded autocomplete) is not a connectivity failure.
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.');
  }

  if (response.ok) {
    try {
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError(response.status, 'invalid_response', 'The server sent an unreadable response.');
    }
  }

  const body: unknown = await response.json().catch(() => null);

  const retryAfter = Number(response.headers.get('Retry-After'));
  const retryAfterS = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null;
  if (isErrorResponse(body)) {
    throw new ApiError(
      response.status,
      body.error.code,
      body.error.message,
      retryAfterS,
      body.weather_request ?? null,
    );
  }
  throw new ApiError(response.status, 'http_error', `Request failed (HTTP ${response.status}).`);
}

function postJson<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
}

/**
 * POST, and if Open-Meteo rate-limited the server, fetch the named forecasts from this browser and
 * repeat the request once with them (see openMeteo.ts).
 */
async function postWithWeatherFallback<T, P extends { forecasts?: SuppliedForecast[] }>(
  path: string,
  payload: P,
  signal?: AbortSignal,
): Promise<T> {
  try {
    return await postJson<T>(path, payload, signal);
  } catch (error) {
    if (!(error instanceof ApiError) || !error.weatherRequest) throw error;
    const forecasts = await fetchForecasts(error.weatherRequest, signal);
    return postJson<T>(path, { ...payload, forecasts }, signal);
  }
}

export const api = {
  geocode: (q: string, signal?: AbortSignal) =>
    request<GeocodeResponse>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }),
  planTrip: (payload: PlanRequest, signal?: AbortSignal) =>
    postWithWeatherFallback<PlanResponse, PlanRequest>('/api/trips/plan', payload, signal),
  heatmap: (payload: HeatmapRequest, signal?: AbortSignal) =>
    postWithWeatherFallback<HeatmapResponse, HeatmapRequest>('/api/trips/heatmap', payload, signal),
};
