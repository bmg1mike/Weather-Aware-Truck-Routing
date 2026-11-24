import type { PlanResponse } from '../api/types';
import { RISK_LEVELS, RISK_STYLES } from '../lib/risk';
import { Icon } from './Icon';

export function RouteResults({
  plan,
  selectedId,
  onSelect,
}: {
  plan: PlanResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="route-results" aria-label="Route options">
      <div className="results-heading"><h2>Your route options</h2><span>{plan.routes.length} available</span></div>
      {plan.routes.length < 3 && <p className="field-help">Only {plan.routes.length} distinct routes available.</p>}
      {plan.no_safe_route && (
        <p className="form-error" role="alert">No safe route at this departure time. The recommended option is the least bad, not a safe route. Review No Travel checkpoints before driving.</p>
      )}
      {plan.routes.length === 0 && <p className="form-error" role="alert">No routes were returned. Try a different origin or destination.</p>}
      {plan.routes.map((route) => {
        const recommended = route.id === plan.recommended_route_id;
        const totalMinutes = Math.round(route.duration_s / 60);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        return (
          <button
            key={route.id}
            type="button"
            className={`route-card ${route.id === selectedId ? 'route-card--selected' : ''}`}
            aria-pressed={route.id === selectedId}
            onClick={() => onSelect(route.id)}
          >
            <span className="route-card-top"><span>ROUTE {route.rank.toString().padStart(2, '0')}</span>{recommended && <span className="route-badge"><Icon name="shield" size={12} />{plan.no_safe_route ? 'Least bad' : 'Recommended'}</span>}</span>
            <span className="route-metrics"><strong>{hours}h {minutes}m</strong><span>{Math.round(route.distance_mi).toLocaleString()} mi</span></span>
            <span className="route-reason">{route.reason}</span>
            <span className="mileage-bar" aria-hidden="true">
              {[...RISK_LEVELS, 'unknown' as const].map((level) => (
                <span key={level} style={{ background: RISK_STYLES[level].colour, flex: level === 'unknown' ? route.summary.unknown_mi : route.summary.miles_by_level[level] }} />
              ))}
            </span>
            <span className="route-risk-detail">
              {RISK_LEVELS.filter((level) => route.summary.miles_by_level[level] > 0).map((level) => (
                <span key={level}>{RISK_STYLES[level].label}: {route.summary.miles_by_level[level].toFixed(1)} mi</span>
              ))}
            </span>
            <span className="route-arrival">Arrive {new Date(route.arrival).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} · Avg. risk {route.summary.avg_risk?.toFixed(2) ?? 'unavailable'}</span>
            {route.summary.unknown_checkpoints > 0 && <span className="data-gap">{route.summary.unknown_checkpoints} checkpoints without a forecast · {route.summary.unknown_mi.toFixed(1)} mi unscored</span>}
          </button>
        );
      })}
    </section>
  );
}
