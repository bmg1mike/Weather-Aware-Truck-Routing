import type { Ref } from 'react';

import type { PlanResponse } from '../api/types';
import { formatDateTime, formatDuration } from '../lib/format';
import { RISK_LEVELS, RISK_STYLES } from '../lib/risk';
import { CheckpointDetails } from './CheckpointDetails';
import { Icon } from './Icon';

export function RouteResults({
  plan,
  selectedId,
  checkpointIndex,
  onSelect,
  onInspect,
  headingRef,
}: {
  plan: PlanResponse;
  selectedId: string | null;
  checkpointIndex: number | null;
  onSelect: (id: string) => void;
  onInspect: (index: number | null) => void;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const selected = plan.routes.find((route) => route.id === selectedId);
  const checkpoint = selected?.checkpoints.find((point) => point.index === checkpointIndex);
  return (
    <section className="route-results" aria-label="Route options">
      <div className="results-heading">
        <h2 id="route-options" tabIndex={-1} ref={headingRef}><span className="step-number">02</span> Compare your routes</h2>
        <span>{plan.routes.length} available</span>
      </div>
      <p className="results-explainer">Weather risk first. Travel time second.</p>
      {plan.routes.length > 0 && plan.routes.length < 3 && <p className="route-notice">Only {plan.routes.length} distinct routes available.</p>}
      {plan.no_safe_route && (
        <div className="safety-banner" role="alert">
          <Icon name="shield" size={21} />
          <div>
            <strong>No safe route at this departure time</strong>
            <p>The least-bad recommendation still has No Travel miles. Consider a different departure.</p>
            <ul>{plan.routes.filter((route) => route.summary.no_travel_stretches.length > 0).map((route) => (
              <li key={route.id}>{route.name}: {route.summary.no_travel_stretches.map(([start, end]) => `mile ${start.toFixed(1)}–${end.toFixed(1)}`).join(', ')}</li>
            ))}</ul>
          </div>
        </div>
      )}
      {plan.routes.length === 0 && <p className="route-notice" role="status">No routes were returned. Try a different origin or destination.</p>}
      {plan.routes.map((route) => {
        const recommended = route.id === plan.recommended_route_id;
        const mileage = [...RISK_LEVELS, 'unknown' as const].map((level) => ({
          level,
          miles: level === 'unknown' ? route.summary.unknown_mi : route.summary.miles_by_level[level],
        })).filter(({ miles }) => miles > 0);
        const description = mileage.map(({ level, miles }) => `${RISK_STYLES[level].label}: ${miles.toFixed(1)} mi`).join(', ');
        return (
          <button
            key={route.id}
            type="button"
            className={`route-card ${route.id === selectedId ? 'route-card--selected' : ''}`}
            aria-label={`Select ${route.name}, rank ${route.rank}${recommended ? plan.no_safe_route ? ', least bad' : ', recommended' : ''}`}
            aria-pressed={route.id === selectedId}
            onClick={() => onSelect(route.id)}
            onMouseMove={() => onSelect(route.id)}
            onFocus={() => onSelect(route.id)}
          >
            <span className="route-card-top">
              <span className="route-name"><span className="rank-badge">{route.rank.toString().padStart(2, '0')}</span>{route.name}</span>
              {recommended && <span className={`route-badge ${plan.no_safe_route ? 'route-badge--blocked' : ''}`}><Icon name="shield" size={12} />{plan.no_safe_route ? 'Least bad' : 'Recommended'}</span>}
            </span>
            <span className="route-metrics"><strong>{formatDuration(route.duration_s)}</strong><span>{route.distance_mi.toLocaleString([], { maximumFractionDigits: 1 })} mi</span><Icon name="arrow" size={17} /></span>
            <span className="route-reason">{route.reason}</span>
            <span className="mileage-bar" role="img" aria-label={`Mileage by weather risk. ${description || 'No scored miles.'}`}>
              {mileage.map(({ level, miles }) => (
                <span key={level} style={{ background: RISK_STYLES[level].colour, flex: miles }} />
              ))}
            </span>
            <span className="route-risk-detail" aria-hidden="true">
              {mileage.map(({ level, miles }) => (
                <span key={level}><span className="risk-dot" style={{ background: RISK_STYLES[level].colour }} />{RISK_STYLES[level].label} <strong>{miles.toFixed(1)}</strong> mi</span>
              ))}
            </span>
            <span className="route-card-footer"><span>Arrival <time dateTime={route.arrival}>{formatDateTime(route.arrival)}</time></span><span>Avg. risk <strong>{route.summary.avg_risk === null ? 'Unavailable' : `${route.summary.avg_risk.toFixed(2)} / 4`}</strong></span></span>
            {(route.summary.unknown_checkpoints > 0 || route.summary.unknown_mi > 0) && <span className="data-gap">{route.summary.unknown_checkpoints} checkpoints without a forecast · {route.summary.unknown_mi.toFixed(1)} mi unscored</span>}
          </button>
        );
      })}
      {selected && (
        <section className="checkpoint-inspector" aria-label={`${selected.name} checkpoints`}>
          <div className="results-heading"><h3>Along {selected.name}</h3><span>{selected.checkpoints.length} checkpoints</span></div>
          <p className="field-help">Select a checkpoint here or on the map to inspect its forecast at your ETA.</p>
          {checkpoint && <CheckpointDetails checkpoint={checkpoint} routeName={selected.name} />}
          <details className="checkpoint-browser">
            <summary><Icon name="location" size={16} /> Browse checkpoints <Icon name="chevron" size={14} /></summary>
            <ol>
              {selected.checkpoints.map((point) => (
                <li key={point.index}>
                  <button type="button" aria-pressed={point.index === checkpointIndex} onClick={() => onInspect(point.index)}>
                    <span className="risk-dot" style={{ background: RISK_STYLES[point.level].colour }} />
                    <span>Mile {point.mile.toFixed(1)}<small>{formatDateTime(point.eta)}</small></span>
                    <span>{RISK_STYLES[point.level].label}</span>
                  </button>
                </li>
              ))}
            </ol>
          </details>
          <p className="eta-assumption">ETAs assume continuous driving, without rest breaks. All displayed times use your browser’s time zone.</p>
        </section>
      )}
    </section>
  );
}
