import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { formatDateTime } from '../lib/format';
import { recommendedRoute, testPlan, testRoute } from '../test/fixtures';
import { RouteResults } from './RouteResults';

describe('RouteResults', () => {
  it('keeps provider names distinct from rank and shows the full comparison and labelled mileage', async () => {
    const select = vi.fn();
    render(<RouteResults plan={testPlan} selectedId="r2" checkpointIndex={null} onSelect={select} onInspect={vi.fn()} />);
    const card = screen.getByRole('button', { name: 'Select Route B, rank 1, recommended' });
    expect(card).toHaveAttribute('aria-pressed', 'true');
    expect(card).toHaveTextContent('2h 10m');
    expect(card).toHaveTextContent('100 mi');
    expect(card).toHaveTextContent(recommendedRoute.reason);
    expect(card).toHaveTextContent(formatDateTime(recommendedRoute.arrival));
    expect(card).toHaveTextContent('0.00 / 4');
    expect(within(card).getByRole('img', { name: /Low: 100.0 mi/ })).toBeInTheDocument();
    expect(screen.getByText('Only 2 distinct routes available.')).toBeInTheDocument();
    await userEvent.hover(screen.getByRole('button', { name: 'Select Route A, rank 2' }));
    expect(select).toHaveBeenLastCalledWith('r1');
  });

  it('presents missing forecasts as unscored rather than Low, with keyboard-accessible inspection', async () => {
    const inspect = vi.fn();
    const unknown = {
      ...testRoute,
      summary: { ...testRoute.summary, miles_by_level: { low: 0, moderate: 0, high: 0, severe: 0, no_travel: 0 }, unknown_mi: 100, avg_risk: null, unknown_checkpoints: 2 },
      checkpoints: testRoute.checkpoints.map((point) => ({ ...point, level: 'unknown' as const, wind_mph: null, gust_mph: null, rain_in_hr: null, snow_in_hr: null, driver: null })),
    };
    render(<RouteResults plan={{ ...testPlan, routes: [unknown], recommended_route_id: 'r1' }} selectedId="r1" checkpointIndex={0} onSelect={vi.fn()} onInspect={inspect} />);
    expect(screen.getByText(/100.0 mi unscored/)).toBeInTheDocument();
    expect(screen.getByText('Unavailable', { selector: '.route-card-footer strong' })).toBeInTheDocument();
    const detail = screen.getByRole('region', { name: 'Route A, checkpoint 1 weather' });
    expect(detail).toHaveTextContent('No forecast');
    expect(detail).toHaveTextContent('Adjacent miles are unscored, not Low risk.');
    expect(within(detail).getAllByText('Unavailable')).toHaveLength(5);
    const user = userEvent.setup();
    await user.click(screen.getByText('Browse checkpoints'));
    const point = screen.getByRole('button', { name: /Mile 100.0.*No forecast/ });
    point.focus();
    await user.keyboard('{Enter}');
    expect(inspect).toHaveBeenCalledWith(1);
  });

  it('names No Travel stretches and labels the recommendation as least bad, not safe', () => {
    const blocked = {
      ...testRoute,
      summary: { ...testRoute.summary, no_travel_stretches: [[25, 50], [75, 100]] as [number, number][] },
    };
    render(<RouteResults plan={{ ...testPlan, routes: [blocked], recommended_route_id: 'r1', no_safe_route: true }} selectedId="r1" checkpointIndex={null} onSelect={vi.fn()} onInspect={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent('No safe route at this departure time');
    expect(screen.getByRole('alert')).toHaveTextContent('Route A: mile 25.0–50.0, mile 75.0–100.0');
    expect(screen.getByRole('button', { name: 'Select Route A, rank 2, least bad' })).toHaveTextContent('Least bad');
    expect(screen.queryByText('Recommended')).not.toBeInTheDocument();
  });

  it('shows an actionable empty state without route cards or checkpoint controls', () => {
    render(<RouteResults plan={{ ...testPlan, routes: [] }} selectedId={null} checkpointIndex={null} onSelect={vi.fn()} onInspect={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('No routes were returned');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
