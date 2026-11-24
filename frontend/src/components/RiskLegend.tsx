import { RISK_LEVELS, RISK_STYLES } from '../lib/risk';

/** Colour plus text label for every level, so colour is never the only signal (spec section 9). */
export function RiskLegend() {
  return (
    <ul className="legend" aria-label="Risk levels">
      {[...RISK_LEVELS, 'unknown' as const].map((level) => (
        <li key={level}>
          <span className="legend-swatch" style={{ background: RISK_STYLES[level].colour }} aria-hidden />
          {RISK_STYLES[level].label}
        </li>
      ))}
    </ul>
  );
}
