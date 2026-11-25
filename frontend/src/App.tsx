import { useMutation, useQuery } from '@tanstack/react-query';
import { type MouseEvent, useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from './api/client';
import type { HeatmapResponse, PlanRequest } from './api/types';
import { HeatmapPanel } from './components/HeatmapPanel';
import { Icon } from './components/Icon';
import { RiskLegend } from './components/RiskLegend';
import { RouteResults } from './components/RouteResults';
import { TripForm } from './components/TripForm';
import { formatDateTime, formatDuration } from './lib/format';
import { toFrames } from './lib/heatmap';
import { HeatmapController } from './map/heatmapLayer';
import { MapView } from './map/MapView';

// Module-level so TanStack Query memoises the typed-array conversion per response.
const selectFrames = (response: HeatmapResponse) => toFrames(response);

/** Desktop shows one view at a time when chosen from the header; stacked layouts just scroll. */
type WorkspaceView = 'planner' | 'map';

export function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkpointIndex, setCheckpointIndex] = useState<number | null>(null);
  const [editing, setEditing] = useState(true);
  const [view, setView] = useState<WorkspaceView>('planner');
  const [focusRequest, setFocusRequest] = useState<{ id: string } | null>(null);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const mapDock = useRef<HTMLDivElement>(null);
  const [mapBottomInset, setMapBottomInset] = useState(320);
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
        max_points: plan.data.corridor.max_grid_points,
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

  useEffect(() => {
    const dock = mapDock.current;
    if (!dock) return;
    const measure = () => {
      const area = dock.offsetParent;
      if (area instanceof HTMLElement) setMapBottomInset(Math.ceil(area.clientHeight - dock.offsetTop + 24));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(dock);
    window.addEventListener('resize', measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);

  /** In-page navigation: switch view, then focus (and on small screens scroll to) the target. */
  const goTo = useCallback((event: MouseEvent<HTMLAnchorElement>, next: WorkspaceView, targetId: string) => {
    event.preventDefault();
    setView(next);
    setFocusRequest({ id: targetId });
  }, []);

  useEffect(() => {
    if (!focusRequest) return;
    const target = document.getElementById(focusRequest.id);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView?.({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, [focusRequest]);

  return (
    <div className={`app-shell ${hasRoutes ? 'app-shell--planned' : ''} ${view === 'map' ? 'app-shell--map-view' : ''}`}>
      <a className="skip-link" href="#trip-planner" onClick={(event) => goTo(event, 'planner', 'trip-planner')}>Skip to trip planner</a>
      <header className="app-header">
        <a className="brand" href="./" aria-label="Waypoint home">
          <span className="brand-symbol"><Icon name="compass" size={27} /></span>
          <span>waypoint<span className="brand-period">.</span></span>
        </a>
        <div className="header-divider" />
        <h1>Weather-aware truck routing</h1>
        <nav className="workspace-nav" aria-label="Workspace">
          <a className={view === 'planner' ? 'workspace-nav-current' : undefined} aria-current={view === 'planner' ? 'true' : undefined} href="#trip-planner" onClick={(event) => goTo(event, 'planner', 'trip-planner')}><Icon name="route" size={16} />Trip planner</a>
          <a className={view === 'map' ? 'workspace-nav-current' : undefined} aria-current={view === 'map' ? 'true' : undefined} href="#journey-map" aria-label="View map and forecast" onClick={(event) => goTo(event, 'map', 'journey-map')}><Icon name="layers" size={16} /><span className="nav-full-label">Map & forecast</span><span className="nav-short-label">Map</span></a>
        </nav>
        <div className="header-end"><span className="header-country">Worldwide</span><span className="version-badge">BETA</span></div>
      </header>

      <div className="workspace">
        <aside className="planner-panel" aria-label="Trip planner" id="trip-planner" tabIndex={-1}>
          <div className="planner-content">
            <div className="eyebrow"><Icon name="compass" size={14} /> THE ROAD, WITH FORESIGHT.</div>
            <h2 className="planner-title">{hasRoutes ? <>Your way <em>forward.</em></> : <>Every mile.<br /> <em>Considered.</em></>}</h2>
            <p className="planner-description">A better perspective on your next trip.<br />Compare the routes. Understand the weather.</p>
            <div className="planner-section-heading"><span className="step-number">01</span><h3>Plan your journey</h3><span className="section-rule" />{hasRoutes ? <button className="edit-trip-button" disabled={plan.isPending} aria-expanded={editing} aria-controls="trip-editor" onClick={() => setEditing(!editing)}>{editing ? 'Hide details' : 'Edit trip'}<Icon name="chevron" size={13} /></button> : <Icon name="route" size={17} />}</div>
            {hasRoutes && !editing && plan.variables && (
              <div className="trip-summary">
                <div className="trip-summary-locations">
                  <div className="trip-summary-stop"><span className="place-marker" /><div><small>FROM</small><span>{plan.variables.origin.label}</span></div></div>
                  <div className="trip-summary-stop trip-summary-stop--destination"><span className="place-marker" /><div><small>TO</small><span>{plan.variables.destination.label}</span></div></div>
                </div>
                <div className="trip-summary-meta">
                  <span><Icon name="clock" size={14} /><time dateTime={plan.variables.departure}>{formatDateTime(plan.variables.departure)}</time></span>
                  <span><Icon name="truck" size={14} />{plan.variables.load_lb.toLocaleString()} lb</span>
                </div>
              </div>
            )}
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
          <footer className="planner-footer"><span className="footer-mark"><Icon name="compass" size={16} /> Foresight for every mile.</span><span>MI · MPH · LB</span></footer>
        </aside>

        <main className="map-area" aria-label="Journey overview" id="journey-map" tabIndex={-1}>
          <MapView routes={plan.data?.routes} selectedId={selectedId} onSelect={selectRoute} checkpointIndex={checkpointIndex} onInspect={inspectCheckpoint} heatmap={heatmapController} bottomInset={mapBottomInset} />
          <div className="map-topline">
            <div className="map-view-label"><Icon name="layers" size={15} /><span>JOURNEY ATLAS</span><span className="map-view-divider" /><span className="map-region">{hasRoutes && plan.variables ? `${plan.variables.origin.label} → ${plan.variables.destination.label}` : 'Worldwide'}</span></div>
          </div>
          {selectedRoute && (
            <section className="map-route-context" aria-label="Selected route">
              <div>
                <span className="map-route-eyebrow">{selectedRoute.id === plan.data?.recommended_route_id ? plan.data.no_safe_route ? 'LEAST-BAD OPTION' : 'RECOMMENDED ROUTE' : 'ALTERNATIVE ROUTE'}</span>
                <h2>{selectedRoute.name}<span>{formatDuration(selectedRoute.duration_s)}<span aria-hidden="true"> / </span>{selectedRoute.distance_mi.toLocaleString([], { maximumFractionDigits: 1 })} mi</span></h2>
              </div>
              <a className="map-compare-link" href="#route-options" aria-label="Compare routes" onClick={(event) => goTo(event, 'planner', 'route-options')}><Icon name="arrow" size={19} /></a>
            </section>
          )}
          {!hasRoutes && !plan.isPending && (
            <div className="map-empty">
              <span className="map-empty-icon"><Icon name="route" size={26} /></span>
              <h2>{plan.data ? <>No route found.<br /><em>A different way?</em></> : <>The road ahead,<br /><em>in focus.</em></>}</h2>
              <p>{plan.data ? 'Try another origin or destination to explore a different journey.' : <>Start with a destination.<br />We’ll help you see the way forward.</>}</p>
              <a className="map-empty-link" href="#trip-planner" onClick={(event) => goTo(event, 'planner', 'trip-planner')}>{plan.data ? 'Adjust your trip' : 'Start with your trip'}<Icon name="arrow" size={16} /></a>
            </div>
          )}
          {plan.isPending && <div className="map-planning-status" role="status"><span className="spinner" /> Comparing routes and checking forecasts</div>}
          <div className="map-bottom" ref={mapDock}>
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
              <div className="map-card-heading"><Icon name="shield" size={14} /><h2>Weather risk</h2></div>
              <RiskLegend />
            </section>
            {!hasRoutes && <section className="forecast-note" aria-label="Forecast availability">
              <span className="forecast-icon"><Icon name="weather" size={24} /></span>
              <div><h2>See beyond the next turn.</h2><p>Plan a trip to see a 48-hour forecast across the whole corridor, hour by hour.</p></div>
              <span className="soon-badge">48 H</span>
            </section>}
          </div>
        </main>
      </div>
    </div>
  );
}
