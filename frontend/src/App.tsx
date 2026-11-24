import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from './api/client';
import type { HeatmapResponse, PlanRequest } from './api/types';
import { HeatmapPanel } from './components/HeatmapPanel';
import { Icon } from './components/Icon';
import { RiskLegend } from './components/RiskLegend';
import { RouteResults } from './components/RouteResults';
import { TripForm } from './components/TripForm';
import { formatDuration } from './lib/format';
import { toFrames } from './lib/heatmap';
import { HeatmapController } from './map/heatmapLayer';
import { MapView } from './map/MapView';

// Module-level so TanStack Query memoises the typed-array conversion per response.
const selectFrames = (response: HeatmapResponse) => toFrames(response);

export function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkpointIndex, setCheckpointIndex] = useState<number | null>(null);
  const [editing, setEditing] = useState(true);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const plan = useMutation({
    mutationFn: (request: PlanRequest) => api.planTrip(request),
    retry: false,
    onSuccess: (data) => {
      setSelectedId(data.recommended_route_id);
      setCheckpointIndex(null);
      setEditing(data.routes.length === 0);
    },
  });
  const selectedRoute = plan.data?.routes.find((route) => route.id === selectedId);
  const hasRoutes = Boolean(plan.data?.routes.length);
  const [heatmapController] = useState(() => new HeatmapController());
  // Requested only after the plan succeeds, so routes are on screen first (spec section 8).
  const heatmap = useQuery({
    queryKey: ['heatmap', plan.submittedAt],
    enabled: hasRoutes && !plan.isPending && Boolean(plan.variables),
    queryFn: ({ signal }) => {
      const routes = plan.data?.routes ?? [];
      const request = plan.variables;
      if (!plan.data || !request) throw new Error('No plan to forecast.');
      return api.heatmap({
        bbox: plan.data.corridor.bbox,
        route_geometries: routes.map((route) => route.geometry),
        start: request.departure,
        load_lb: request.load_lb,
      }, signal);
    },
    select: selectFrames,
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    heatmapController.setData(
      hasRoutes ? heatmap.data ?? null : null,
      plan.data?.routes ?? [],
      plan.variables?.departure ?? null,
      selectedId,
    );
    // selectedId is synced separately so selecting a route does not rebuild the raster.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatmapController, heatmap.data, hasRoutes, plan.data, plan.variables]);
  useEffect(() => heatmapController.setSelected(selectedId), [heatmapController, selectedId]);
  const selectRoute = useCallback((id: string) => {
    if (id !== selectedId) {
      setSelectedId(id);
      setCheckpointIndex(null);
    }
  }, [selectedId]);
  const inspectCheckpoint = useCallback((id: string, index: number | null) => {
    setSelectedId(id);
    setCheckpointIndex(index);
  }, []);

  useEffect(() => {
    if (plan.data) resultsHeading.current?.focus();
  }, [plan.data]);

  return (
    <div className={`app-shell ${hasRoutes ? 'app-shell--planned' : ''}`}>
      <a className="skip-link" href="#trip-planner">Skip to trip planner</a>
      <header className="app-header">
        <a className="brand" href="./" aria-label="Waypoint home">
          <span className="brand-symbol"><Icon name="compass" size={27} /></span>
          <span>waypoint<span className="brand-period">.</span></span>
        </a>
        <div className="header-divider" />
        <h1>Weather-aware truck routing</h1>
        <div className="header-end"><span className="header-country">Built for the long haul</span><span className="version-badge">BETA</span></div>
      </header>

      <div className="workspace">
        <aside className="planner-panel" aria-label="Trip planner" id="trip-planner" tabIndex={-1}>
          <div className="planner-content">
            <div className="eyebrow"><span className="tiny-cross">+</span> A LITTLE FORESIGHT. A BETTER JOURNEY.</div>
            <h2 className="planner-title">Know what’s<br />{' '}on the <em>way.</em></h2>
            <p className="planner-description">A clearer view of the road ahead.<br />{' '}Compare routes. Stay ahead of the weather.</p>
            <div className="planner-section-heading"><span className="step-number">01</span><h3>Plan your journey</h3><span className="section-rule" />{hasRoutes ? <button className="edit-trip-button" disabled={plan.isPending} aria-expanded={editing} aria-controls="trip-editor" onClick={() => setEditing(!editing)}>{editing ? 'Hide details' : 'Edit trip'}<Icon name="chevron" size={13} /></button> : <Icon name="route" size={17} />}</div>
            {hasRoutes && !editing && plan.variables && <p className="trip-summary"><span>{plan.variables.origin.label}</span><Icon name="arrow" size={15} /><span>{plan.variables.destination.label}</span></p>}
            <div id="trip-editor" hidden={!editing}><TripForm onSubmit={(request) => plan.mutate(request)} pending={plan.isPending} /></div>

            {plan.isError && (
              <div className="api-error" role="alert">
                <strong>We couldn’t plan this trip</strong>
                <p>{plan.error.message}</p>
                {plan.error instanceof ApiError && plan.error.retryAfterS && <p>Try again in {plan.error.retryAfterS} seconds.</p>}
                {plan.error instanceof ApiError && plan.error.retryable && <button className="text-button" onClick={() => plan.variables && plan.mutate(plan.variables)}>Try again <Icon name="arrow" size={14} /></button>}
              </div>
            )}
            {plan.isPending && <div className="loading-routes" role="status" aria-label="Comparing routes"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /><p>Finding the road with fewer surprises…<br />Routes and forecasts can take a few seconds.</p></div>}
            {plan.data && !plan.isPending && <RouteResults plan={plan.data} selectedId={selectedId} checkpointIndex={checkpointIndex} onSelect={selectRoute} onInspect={setCheckpointIndex} headingRef={resultsHeading} />}
          </div>
          <footer className="planner-footer"><span className="footer-mark"><Icon name="compass" size={16} /> Foresight for every mile.</span><span>US / MI / LB</span></footer>
        </aside>

        <main className="map-area" aria-label="Journey overview">
          <MapView routes={plan.data?.routes} selectedId={selectedId} onSelect={selectRoute} checkpointIndex={checkpointIndex} onInspect={inspectCheckpoint} heatmap={heatmapController} />
          <div className="map-topline">
            <div className="map-view-label"><span className="map-status-dot" /><span>THE BIG PICTURE</span><span className="map-view-divider" /><span className="map-region">Contiguous United States</span></div>
            <span className="map-mode"><Icon name="layers" size={15} /> Atlas view</span>
          </div>
          {!hasRoutes && !plan.isPending && (
            <div className="map-empty" aria-hidden="true">
              <span className="map-empty-icon"><Icon name="route" size={26} /></span>
              <h2>{plan.data ? <>No route found.<br /><em>A different way?</em></> : <>Your next chapter,<br /><em>mapped out.</em></>}</h2>
              <p>{plan.data ? 'Try another origin or destination to explore a different journey.' : <>Start with a destination.<br />We’ll help you see the way forward.</>}</p>
              <span className="map-empty-coordinate">39.5000° N &nbsp; 98.5000° W</span>
            </div>
          )}
          {plan.isPending && <div className="map-planning-status" role="status"><span className="spinner" /> Comparing routes and checking forecasts</div>}
          <div className="map-bottom">
            {hasRoutes && !plan.isPending && (
              <HeatmapPanel
                key={plan.submittedAt}
                status={heatmap.isError ? 'error' : heatmap.data ? 'ready' : 'loading'}
                frames={heatmap.data ?? null}
                start={plan.variables?.departure ?? null}
                controller={heatmapController}
                error={heatmap.error}
                onRetry={() => void heatmap.refetch()}
              />
            )}
            <section className="map-legend" aria-label="Weather risk key">
              <div className="map-card-heading"><Icon name="shield" size={15} /><h2>Every mile, in perspective.</h2><span>WEATHER RISK</span></div>
              <RiskLegend />
            </section>
            {selectedRoute ? <section className="forecast-note selected-route-note" aria-label="Selected route">
              <span className="forecast-icon"><Icon name="route" size={24} /></span>
              <div><h2>{selectedRoute.name} <span>· {formatDuration(selectedRoute.duration_s)} · {selectedRoute.distance_mi.toLocaleString([], { maximumFractionDigits: 1 })} mi</span></h2><p>Select a checkpoint to inspect the weather at your ETA. Dashed grey segments have no forecast.</p></div>
              <a className="map-compare-link" href="#route-options">Compare routes <Icon name="arrow" size={15} /></a>
            </section> : <section className="forecast-note" aria-label="Forecast availability">
              <span className="forecast-icon"><Icon name="weather" size={24} /></span>
              <div><h2>The weather moves. Your plan should, too.</h2><p>Plan a trip to see a 48-hour forecast across the whole corridor, hour by hour.</p></div>
              <span className="soon-badge">48 H</span>
            </section>}
          </div>
        </main>
      </div>
    </div>
  );
}
