import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { api, ApiError } from './api/client';

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
    expect(screen.getByText(/no forecast layer is displayed yet/i)).toBeInTheDocument();
  });

  it('explains an unfinished planning service without substituting demo routes', async () => {
    vi.spyOn(api, 'geocode').mockImplementation(async (q) => ({
      results: [q.startsWith('Dal')
        ? { label: 'Dallas, TX', lat: 32.7767, lon: -96.797 }
        : { label: 'Denver, CO', lat: 39.7392, lon: -104.9903 }],
    }));
    vi.spyOn(api, 'planTrip').mockRejectedValue(new ApiError(501, 'not_implemented', 'Not implemented.'));
    render(<QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider>);
    const user = userEvent.setup();
    await user.type(screen.getByRole('combobox', { name: 'Origin' }), 'Dallas');
    await user.click(await screen.findByRole('option', { name: 'Dallas, TX' }));
    await user.type(screen.getByRole('combobox', { name: 'Destination' }), 'Denver');
    await user.click(await screen.findByRole('option', { name: 'Denver, CO' }));
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Trip planning is on the way');
    expect(screen.queryByRole('region', { name: 'Route options' })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveValue('Dallas, TX');
  });
});
