import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { api, ApiError } from './api/client';
import type { PlanResponse } from './api/types';
import { testHeatmap, testPlan } from './test/fixtures';

async function enterTrip(user: ReturnType<typeof userEvent.setup>) {
  vi.spyOn(api, 'geocode').mockImplementation(async (q) => ({
    results: [q.startsWith('Dal')
      ? { label: 'Dallas, TX', lat: 32.7767, lon: -96.797 }
      : { label: 'Denver, CO', lat: 39.7392, lon: -104.9903 }],
  }));
  await user.type(screen.getByRole('combobox', { name: 'Origin' }), 'Dallas');
  await user.click(await screen.findByRole('option', { name: 'Dallas, TX' }));
  await user.type(screen.getByRole('combobox', { name: 'Destination' }), 'Denver');
  await user.click(await screen.findByRole('option', { name: 'Denver, CO' }));
  await user.click(screen.getByRole('button', { name: 'Find my route' }));
}

describe('App shell', () => {
  it('renders the planner panel, map region and labelled legend', () => {
    render(<QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider>);
    expect(screen.getByRole('heading', { name: /weather-aware truck routing/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /route map/i })).toBeInTheDocument();
    const legend = screen.getByRole('list', { name: /risk levels/i });
    for (const label of ['Low', 'Moderate', 'High', 'Severe', 'No Travel', 'No forecast']) {
      expect(legend).toHaveTextContent(label);
    }
    expect(screen.getByRole('combobox', { name: 'Origin' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Find my route' })).toBeInTheDocument();
    expect(screen.getByText(/48-hour forecast across the whole corridor/i)).toBeInTheDocument();
  });

  it('renders routes before requesting the heatmap once, and does not refetch on selection', async () => {
    let finishPlan: (response: PlanResponse) => void = () => { throw new Error('Plan not pending'); };
    const planTrip = vi.spyOn(api, 'planTrip').mockReturnValue(new Promise((resolve) => { finishPlan = resolve; }));
    const heatmap = vi.spyOn(api, 'heatmap').mockResolvedValue(testHeatmap);
    render(<QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider>);
    const user = userEvent.setup();
    await enterTrip(user);
    expect(screen.getByRole('status', { name: 'Comparing routes' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Route options' })).not.toBeInTheDocument();
    expect(heatmap).not.toHaveBeenCalled();
    await act(async () => finishPlan(testPlan));
    const recommended = await screen.findByRole('button', { name: 'Select Route B, rank 1, recommended' });
    expect(recommended).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: /Compare your routes/ })).toHaveFocus();
    expect(screen.getByRole('region', { name: 'Selected route' })).toHaveTextContent('Route B');
    // The heatmap is requested only after routes are on screen, with the plan's corridor.
    expect(await screen.findByRole('slider', { name: 'Forecast hour' })).toBeInTheDocument();
    expect(heatmap).toHaveBeenCalledTimes(1);
    expect(heatmap.mock.calls[0]?.[0]).toEqual({
      bbox: testPlan.corridor.bbox,
      route_geometries: testPlan.routes.map((route) => route.geometry),
      start: planTrip.mock.calls[0]?.[0].departure,
      load_lb: planTrip.mock.calls[0]?.[0].load_lb,
      max_points: testPlan.corridor.max_grid_points,
    });
    await user.click(screen.getByRole('button', { name: 'Select Route A, rank 2' }));
    expect(screen.getByRole('region', { name: 'Selected route' })).toHaveTextContent('Route A');
    expect(planTrip).toHaveBeenCalledTimes(1);
    expect(heatmap).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Edit trip' }));
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveValue('Dallas, TX');
  });

  it('retains the trip on provider errors and retries with the same validated request', async () => {
    const planTrip = vi.spyOn(api, 'planTrip')
      .mockRejectedValueOnce(new ApiError(503, 'provider_rate_limited', 'Weather provider busy.', 60))
      .mockResolvedValue(testPlan);
    render(<QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider>);
    const user = userEvent.setup();
    await enterTrip(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('Weather provider busy.');
    expect(screen.getByRole('alert')).toHaveTextContent('Try again in 60 seconds.');
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveValue('Dallas, TX');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Select Route B, rank 1, recommended' })).toBeInTheDocument();
    expect(planTrip.mock.calls[0]).toEqual(planTrip.mock.calls[1]);
  });
});
