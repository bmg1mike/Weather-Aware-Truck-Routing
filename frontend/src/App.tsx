import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError } from './api/client';
import type { PlanRequest } from './api/types';
import { Icon } from './components/Icon';
import { RiskLegend } from './components/RiskLegend';
import { RouteResults } from './components/RouteResults';
import { TripForm } from './components/TripForm';
import { MapView } from './map/MapView';

export function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const plan = useMutation({
    mutationFn: (request: PlanRequest) => api.planTrip(request),
    retry: false,
    onSuccess: (data) => setSelectedId(data.recommended_route_id),
  });

  return (
    <div className="app-shell">
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
            <div className="planner-section-heading"><span className="step-number">01</span><h3>Plan your journey</h3><span className="section-rule" /><Icon name="route" size={17} /></div>
            <TripForm onSubmit={(request) => plan.mutate(request)} pending={plan.isPending} />

            {plan.isError && (
              <div className="api-error" role="alert">
                <strong>{plan.error instanceof ApiError && plan.error.code === 'not_implemented' ? 'Trip planning is on the way' : 'We couldn’t plan this trip'}</strong>
                <p>{plan.error instanceof ApiError && plan.error.code === 'not_implemented' ? 'The planning service is still being built. Your trip details are ready, but live routes and forecasts aren’t available yet.' : plan.error.message}</p>
                {plan.error instanceof ApiError && plan.error.retryAfterS && <p>Try again in {plan.error.retryAfterS} seconds.</p>}
                {plan.error instanceof ApiError && plan.error.retryable && <button className="text-button" onClick={() => plan.variables && plan.mutate(plan.variables)}>Try again <Icon name="arrow" size={14} /></button>}
              </div>
            )}
            {plan.isPending && <div className="loading-routes" role="status"><span className="skeleton" /><span className="skeleton" /><p>Finding the road with fewer surprises…</p></div>}
            {plan.data && !plan.isPending && <RouteResults plan={plan.data} selectedId={selectedId} onSelect={setSelectedId} />}
          </div>
          <footer className="planner-footer"><span className="footer-mark"><Icon name="compass" size={16} /> Foresight for every mile.</span><span>US / MI / LB</span></footer>
        </aside>

        <main className="map-area" aria-label="Journey overview">
          <MapView routes={plan.data?.routes} selectedId={selectedId} onSelect={setSelectedId} />
          <div className="map-topline">
            <div className="map-view-label"><span className="map-status-dot" /><span>THE BIG PICTURE</span><span className="map-view-divider" /><span className="map-region">Contiguous United States</span></div>
            <span className="map-mode"><Icon name="layers" size={15} /> Atlas view</span>
          </div>
          {!plan.data?.routes.length && (
            <div className="map-empty" aria-hidden="true">
              <span className="map-empty-icon"><Icon name="route" size={26} /></span>
              <h2>Your next chapter,<br /><em>mapped out.</em></h2>
              <p>Start with a destination.<br />We’ll help you see the way forward.</p>
              <span className="map-empty-coordinate">39.5000° N &nbsp; 98.5000° W</span>
            </div>
          )}
          <div className="map-bottom">
            <section className="map-legend" aria-label="Weather risk key">
              <div className="map-card-heading"><Icon name="shield" size={15} /><h2>Every mile, in perspective.</h2><span>WEATHER RISK</span></div>
              <RiskLegend />
            </section>
            <section className="forecast-note" aria-label="Forecast availability">
              <span className="forecast-icon"><Icon name="weather" size={24} /></span>
              <div><h2>The weather moves. Your plan should, too.</h2><p>48-hour corridor forecasts are coming next. No forecast layer is displayed yet.</p></div>
              <span className="soon-badge">UP NEXT</span>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
