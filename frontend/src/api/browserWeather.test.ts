import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from './client';
import type { PlanRequest, WeatherRequest } from './types';

const plan: PlanRequest = {
  origin: { label: 'Dallas, TX', lat: 32.7767, lon: -96.797 },
  destination: { label: 'Denver, CO', lat: 39.7392, lon: -104.9903 },
  departure: '2026-11-25T06:00:00-06:00',
  load_lb: 42000,
  interval_mi: 25,
};

const weatherRequest: WeatherRequest = {
  cells: [[32.8, -96.8], [33.1, -97.2]],
  start_hour: '2026-11-25T12:00',
  end_hour: '2026-11-25T14:00',
};

function hourly(wind: number) {
  return {
    time: ['2026-11-25T12:00', '2026-11-25T13:00', '2026-11-25T14:00'],
    wind_speed_10m: [wind, wind, wind],
    wind_gusts_10m: [wind, wind, wind],
    rain: [0, 0, 0],
    showers: [0, 0, 0],
    snowfall: [0, 0, 0],
  };
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

const rateLimited = () =>
  json(503, {
    error: { code: 'provider_rate_limited', message: 'Open-Meteo is busy. Please retry in about 10 hours.' },
    weather_request: weatherRequest,
  }, { 'Retry-After': '37632' });

afterEach(() => vi.unstubAllGlobals());

describe('browser weather fallback', () => {
  it('fetches the requested forecasts itself and repeats the plan with them', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(rateLimited())
      .mockResolvedValueOnce(json(200, [{ hourly: hourly(10) }, { hourly: hourly(20) }]))
      .mockResolvedValueOnce(json(200, { recommended_route_id: 'r1' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.planTrip(plan)).resolves.toEqual({ recommended_route_id: 'r1' });

    const forecastUrl = new URL(fetchMock.mock.calls[1]?.[0] as string);
    expect(forecastUrl.origin + forecastUrl.pathname).toBe('https://api.open-meteo.com/v1/forecast');
    expect(forecastUrl.searchParams.get('latitude')).toBe('32.8,33.1');
    expect(forecastUrl.searchParams.get('longitude')).toBe('-96.8,-97.2');
    expect(forecastUrl.searchParams.get('start_hour')).toBe('2026-11-25T12:00');
    expect(forecastUrl.searchParams.get('wind_speed_unit')).toBe('mph');

    const [retryUrl, retryInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(retryUrl).toBe('/api/trips/plan');
    const body = JSON.parse(retryInit.body as string) as PlanRequest;
    expect(body.forecasts).toEqual([
      { lat: 32.8, lon: -96.8, hourly: hourly(10) },
      { lat: 33.1, lon: -97.2, hourly: hourly(20) },
    ]);
  });

  it('splits more than 100 cells into several Open-Meteo requests', async () => {
    const cells = Array.from({ length: 150 }, (_, i): [number, number] => [30 + i / 10, -100]);
    const fetchMock = vi.fn(async (...[url]: [string, RequestInit?]) => {
      if (url.startsWith('https://api.open-meteo.com')) {
        const count = new URL(url).searchParams.get('latitude')!.split(',').length;
        return json(200, Array.from({ length: count }, () => ({ hourly: hourly(5) })));
      }
      return fetchMock.mock.calls.length === 1
        ? json(503, { error: { code: 'provider_rate_limited', message: 'busy' }, weather_request: { ...weatherRequest, cells } })
        : json(200, { ok: true });
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.planTrip(plan);

    const meteoCalls = fetchMock.mock.calls.filter(([url]) => url.startsWith('https://api.open-meteo.com'));
    expect(meteoCalls).toHaveLength(2);
    const retry = JSON.parse((fetchMock.mock.calls.at(-1)?.[1] as RequestInit).body as string) as PlanRequest;
    expect(retry.forecasts).toHaveLength(150);
  });

  it('reports a rate limit when the browser is also rate-limited', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(rateLimited())
      .mockResolvedValueOnce(json(429, { error: true, reason: 'Too many requests' })));

    const error = (await api.planTrip(plan).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('provider_rate_limited');
    expect(error.retryable).toBe(true);
  });

  it('does not fetch weather for other errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json(503, { error: { code: 'provider_rate_limited', message: 'TomTom is busy.' } }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await api.planTrip(plan).catch(() => undefined);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
