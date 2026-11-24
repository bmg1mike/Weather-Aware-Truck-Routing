import type { Checkpoint } from '../api/types';
import { formatDateTime } from '../lib/format';
import { RISK_STYLES } from '../lib/risk';

function measurement(value: number | null, digits: number, unit: string): string {
  return value === null ? 'Unavailable' : `${value.toFixed(digits)} ${unit}`;
}

export function CheckpointDetails({ checkpoint, routeName }: { checkpoint: Checkpoint; routeName: string }) {
  const style = RISK_STYLES[checkpoint.level];
  return (
    <section className="checkpoint-detail" aria-label={`${routeName}, checkpoint ${checkpoint.index + 1} weather`}>
      <div className="checkpoint-detail-top"><span>{routeName} / MILE {checkpoint.mile.toFixed(1)}</span><span className="risk-pill"><span style={{ background: style.colour }} />{style.label}</span></div>
      <h3>Weather along the way</h3>
      <p className="checkpoint-eta">ETA <time dateTime={checkpoint.eta}>{formatDateTime(checkpoint.eta)}</time></p>
      {checkpoint.level === 'unknown' && <p className="checkpoint-gap">Forecast unavailable at this ETA. Adjacent miles are unscored, not Low risk.</p>}
      <dl className="weather-measurements">
        <div><dt>Wind</dt><dd>{measurement(checkpoint.wind_mph, 1, 'mph')}</dd></div>
        <div><dt>Gusts</dt><dd>{measurement(checkpoint.gust_mph, 1, 'mph')}</dd></div>
        <div><dt>Rain</dt><dd>{measurement(checkpoint.rain_in_hr, 3, 'in/hr')}</dd></div>
        <div><dt>Snow</dt><dd>{measurement(checkpoint.snow_in_hr, 3, 'in/hr')}</dd></div>
      </dl>
      <p className="checkpoint-driver">Risk driver <strong>{checkpoint.driver ? { wind: 'Wind', rain: 'Rain', snow: 'Snow' }[checkpoint.driver] : 'Unavailable'}</strong></p>
    </section>
  );
}
