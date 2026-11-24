import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from '../api/client';
import { TripForm } from './TripForm';

const dallas = { label: 'Dallas, TX', lat: 32.7767, lon: -96.797 };
const denver = { label: 'Denver, CO', lat: 39.7392, lon: -104.9903 };

afterEach(() => vi.useRealTimers());

function renderForm() {
  const submit = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TripForm onSubmit={submit} pending={false} />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), submit };
}

async function selectPlaces(user: ReturnType<typeof userEvent.setup>) {
  vi.spyOn(api, 'geocode').mockImplementation(async (q) => ({
    results: q.startsWith('Dal') ? [dallas] : [denver],
  }));
  await user.type(screen.getByRole('combobox', { name: 'Origin' }), 'Dallas');
  await user.click(await screen.findByRole('option', { name: 'Dallas, TX' }));
  await user.type(screen.getByRole('combobox', { name: 'Destination' }), 'Denver');
  await user.click(await screen.findByRole('option', { name: 'Denver, CO' }));
}

describe('TripForm', () => {
  it('requires resolved locations instead of sending free-text addresses', async () => {
    const { user, submit } = renderForm();
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose an origin from the address suggestions.');
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveFocus();
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveAttribute('aria-invalid', 'true');
    expect(submit).not.toHaveBeenCalled();
  });

  it('waits the full 300 ms and resets the debounce when the address changes', async () => {
    vi.useFakeTimers();
    const geocode = vi.spyOn(api, 'geocode').mockResolvedValue({ results: [denver] });
    renderForm();
    const input = screen.getByRole('combobox', { name: 'Origin' });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'Dallas' } });
    act(() => vi.advanceTimersByTime(299));
    expect(geocode).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'Denver' } });
    act(() => vi.advanceTimersByTime(299));
    expect(geocode).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(geocode).toHaveBeenCalledExactlyOnceWith('Denver', expect.any(AbortSignal));
  });

  it('debounces autocomplete, requires three characters and supports keyboard selection', async () => {
    const geocode = vi.spyOn(api, 'geocode').mockResolvedValue({ results: [dallas] });
    const { user } = renderForm();
    const input = screen.getByRole('combobox', { name: 'Origin' });
    await user.type(input, 'Da');
    expect(geocode).not.toHaveBeenCalled();
    await user.type(input, 'llas');
    await screen.findByRole('option', { name: 'Dallas, TX' });
    expect(geocode).toHaveBeenCalledExactlyOnceWith('Dallas', expect.any(AbortSignal));
    await user.keyboard('{Escape}');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(input).toHaveValue('Dallas, TX');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('swaps selected endpoints and submits the chosen interval and offset-aware departure', async () => {
    const { user, submit } = renderForm();
    await selectPlaces(user);
    await user.click(screen.getByRole('button', { name: 'Swap origin and destination' }));
    expect(screen.getByRole('combobox', { name: 'Origin' })).toHaveValue('Denver, CO');
    await user.click(screen.getByRole('radio', { name: '10 miles' }));
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(submit).toHaveBeenCalledWith({
      origin: denver,
      destination: dallas,
      departure: expect.stringMatching(/Z$/),
      load_lb: 40000,
      interval_mi: 10,
    });
  });

  it('rejects invalid load weights and departures before calling the API', async () => {
    const { user, submit } = renderForm();
    await selectPlaces(user);
    const load = screen.getByRole('spinbutton', { name: 'Load weight' });
    await user.clear(load);
    await user.type(load, '80001');
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(screen.getByRole('alert')).toHaveTextContent('between 1 and 80,000');
    await user.clear(screen.getByLabelText(/Departure time/));
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(screen.getByRole('alert')).toHaveTextContent('between now and seven days');
    expect(submit).not.toHaveBeenCalled();
  });

  it('rejects identical coordinates and invalidates a location when its selected text is edited', async () => {
    const { user, submit } = renderForm();
    await selectPlaces(user);
    const destination = screen.getByRole('combobox', { name: 'Destination' });
    await user.clear(destination);
    await user.type(destination, 'Dallas');
    await user.click(await screen.findByRole('option', { name: 'Dallas, TX' }));
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(screen.getByRole('alert')).toHaveTextContent('must be different');
    expect(destination).toHaveFocus();
    await user.type(destination, 'x');
    await user.click(screen.getByRole('button', { name: 'Find my route' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a destination from the address suggestions.');
    expect(submit).not.toHaveBeenCalled();
  });

  it('surfaces geocoding failures and lets the driver retry', async () => {
    const geocode = vi.spyOn(api, 'geocode')
      .mockRejectedValueOnce(new ApiError(503, 'provider_rate_limited', 'Address provider busy.'))
      .mockResolvedValue({ results: [dallas] });
    const { user } = renderForm();
    await user.type(screen.getByRole('combobox', { name: 'Origin' }), 'Dallas');
    expect(await screen.findByText('Address provider busy.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(geocode).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('option', { name: 'Dallas, TX' })).toBeInTheDocument();
  });
});
