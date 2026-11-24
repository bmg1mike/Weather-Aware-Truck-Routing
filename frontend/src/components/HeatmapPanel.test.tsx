import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { toFrames } from '../lib/heatmap';
import { HeatmapPanel } from './HeatmapPanel';

const frames = toFrames({
  grid: { lats: [40], lons: [-100], spacing_deg: 0.3 },
  hours: 49,
  risk: Array.from({ length: 49 }, () => [0]),
  wind: Array.from({ length: 49 }, () => [5]),
  rain: Array.from({ length: 49 }, () => [0]),
  snow: Array.from({ length: 49 }, () => [0]),
});
const START = '2026-11-25T06:00:00-06:00';

function setup(props: Partial<Parameters<typeof HeatmapPanel>[0]> = {}) {
  const controller = { show: vi.fn() };
  const fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
  render(<HeatmapPanel status="ready" frames={frames} start={START} controller={controller} onRetry={vi.fn()} {...props} />);
  return { controller, fetchSpy };
}

describe('HeatmapPanel', () => {
  it('starts at departure (hour 0) and draws that frame', () => {
    const { controller } = setup();
    const slider = screen.getByRole('slider', { name: 'Forecast hour' });
    expect(slider).toHaveAttribute('min', '0');
    expect(slider).toHaveAttribute('max', '48');
    expect(slider).toHaveValue('0');
    expect(screen.getByText(new Date(START).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }), { exact: false })).toBeInTheDocument();
    expect(controller.show).toHaveBeenLastCalledWith(0, 'risk');
  });

  it('changes the active frame on drag without any network request', () => {
    const { controller, fetchSpy } = setup();
    const slider = screen.getByRole('slider', { name: 'Forecast hour' });
    for (const hour of [1, 7, 23, 48]) fireEvent.change(slider, { target: { value: String(hour) } });
    expect(controller.show).toHaveBeenLastCalledWith(48, 'risk');
    expect(screen.getByText('+48 h')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('plays through the hours and stops at the end', () => {
    vi.useFakeTimers();
    try {
      const { controller } = setup();
      fireEvent.click(screen.getByRole('button', { name: 'Play forecast' }));
      act(() => { vi.advanceTimersByTime(3 * 600); });
      expect(controller.show).toHaveBeenLastCalledWith(3, 'risk');
      fireEvent.click(screen.getByRole('button', { name: 'Pause forecast' }));
      act(() => { vi.advanceTimersByTime(5 * 600); });
      expect(controller.show).toHaveBeenLastCalledWith(3, 'risk');
      fireEvent.change(screen.getByRole('slider', { name: 'Forecast hour' }), { target: { value: '47' } });
      fireEvent.click(screen.getByRole('button', { name: 'Play forecast' }));
      act(() => { vi.advanceTimersByTime(10 * 600); });
      expect(controller.show).toHaveBeenLastCalledWith(48, 'risk');
      expect(screen.getByRole('button', { name: 'Play forecast' })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('switches layers and shows that layer’s scale', async () => {
    const { controller } = setup();
    await userEvent.setup().click(screen.getByRole('radio', { name: 'Wind' }));
    expect(controller.show).toHaveBeenLastCalledWith(0, 'wind');
    expect(screen.getByLabelText('Wind scale')).toHaveTextContent('60+ mph');
  });

  it('shows loading and retryable error states without a slider', async () => {
    setup({ status: 'loading', frames: null });
    expect(screen.getByRole('status')).toHaveTextContent(/loading the 48-hour forecast/i);
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  });

  it('offers a retry when the heatmap request fails', async () => {
    const onRetry = vi.fn();
    setup({ status: 'error', frames: null, error: new ApiError(503, 'provider_rate_limited', 'Open-Meteo is busy.'), onRetry });
    expect(screen.getByRole('alert')).toHaveTextContent('Open-Meteo is busy.');
    await userEvent.setup().click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
