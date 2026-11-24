import { describe, expect, it, vi } from 'vitest';

import { api, ApiError } from './client';
import type { PlanRequest } from './types';

function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status, headers }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const plan: PlanRequest = {
  origin: { label: 'Dallas, TX', lat: 32.7767, lon: -96.797 },
  destination: { label: 'Denver, CO', lat: 39.7392, lon: -104.9903 },
  departure: '2026-11-25T06:00:00-06:00',
  load_lb: 42000,
  interval_mi: 25,
};

describe('api client', () => {
  it('posts JSON to the plan endpoint and returns the body', async () => {
    const fetchMock = stubFetch(200, { recommended_route_id: 'r1' });
    await expect(api.planTrip(plan)).resolves.toEqual({ recommended_route_id: 'r1' });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/trips/plan');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(plan);
  });

  it('encodes the geocode query', async () => {
    const fetchMock = stubFetch(200, { results: [] });
    await api.geocode('St. Louis, MO');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/geocode?q=St.%20Louis%2C%20MO');
  });

  it('turns the error envelope into an ApiError', async () => {
    stubFetch(400, { error: { code: 'validation_error', message: 'load_lb: too heavy' } });
    const error = await api.planTrip(plan).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: 'validation_error', message: 'load_lb: too heavy' });
    expect((error as ApiError).retryable).toBe(false);
  });

  it('keeps the retry hint for rate limits', async () => {
    stubFetch(503, { error: { code: 'provider_rate_limited', message: 'busy' } }, { 'Retry-After': '60' });
    const error = (await api.planTrip(plan).catch((e: unknown) => e)) as ApiError;
    expect(error.retryAfterS).toBe(60);
    expect(error.retryable).toBe(true);
  });

  it('handles non-envelope failures', async () => {
    stubFetch(502, undefined);
    await expect(api.planTrip(plan)).rejects.toMatchObject({ status: 502, code: 'http_error' });
  });

  it('lets an aborted request reject with AbortError, not a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')));
    await expect(api.geocode('Dallas')).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('rejects an unreadable success body instead of returning null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json', { status: 200 })));
    await expect(api.planTrip(plan)).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('reports network failures as retryable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const error = (await api.planTrip(plan).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('network_error');
    expect(error.retryable).toBe(true);
  });
});
