import { useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { type HeatmapFrames, type HeatmapLayerKey, VALUE_SCALES } from '../lib/heatmap';
import { Icon } from './Icon';

export interface HeatmapView {
  /** Draws an in-memory frame. Must never touch the network. */
  show(hour: number, layer: HeatmapLayerKey): void;
}

const LAYERS: { key: HeatmapLayerKey; label: string }[] = [
  { key: 'risk', label: 'Risk' },
  { key: 'wind', label: 'Wind' },
  { key: 'rain', label: 'Rain' },
  { key: 'snow', label: 'Snow' },
];
const LAST_HOUR = 48;
const PLAY_STEP_MS = 600;

function hourLabel(start: string, hour: number) {
  const time = new Date(Date.parse(start) + hour * 3_600_000);
  return {
    time: time.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }),
    date: time.toLocaleDateString([], { month: 'short', day: 'numeric' }),
  };
}

function ValueScaleKey({ layer }: { layer: Exclude<HeatmapLayerKey, 'risk'> }) {
  const scale = VALUE_SCALES[layer];
  const gradient = scale.stops.map(([r, g, b]) => `rgb(${r} ${g} ${b})`).join(', ');
  return (
    <div className="heatmap-scale" aria-label={`${scale.label} scale`}>
      <span>0</span>
      <span className="heatmap-scale-bar" style={{ background: `linear-gradient(90deg, transparent, ${gradient})` }} />
      <span>{scale.max}+ {scale.unit}</span>
    </div>
  );
}

export function HeatmapPanel({
  status,
  frames,
  start,
  controller,
  error,
  onRetry,
}: {
  status: 'loading' | 'error' | 'ready';
  frames: HeatmapFrames | null;
  start: string | null;
  controller: HeatmapView;
  error?: Error | null;
  onRetry: () => void;
}) {
  const [hour, setHour] = useState(0);
  const [layer, setLayer] = useState<HeatmapLayerKey>('risk');
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (frames) controller.show(hour, layer);
  }, [controller, frames, hour, layer]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setHour((current) => {
        if (current >= LAST_HOUR - 1) setPlaying(false);
        return Math.min(current + 1, LAST_HOUR);
      });
    }, PLAY_STEP_MS);
    return () => window.clearInterval(timer);
  }, [playing]);

  if (status === 'loading') {
    return (
      <section className="heatmap-panel heatmap-panel--status" aria-label="Corridor forecast">
        <p role="status"><span className="spinner" /> Loading the 48-hour forecast for this corridor…</p>
      </section>
    );
  }
  if (status === 'error' || !frames || !start) {
    return (
      <section className="heatmap-panel heatmap-panel--status" aria-label="Corridor forecast">
        <div role="alert">
          <strong>The corridor forecast didn’t load.</strong>
          <p>{error?.message ?? 'Please try again.'}</p>
          {(!(error instanceof ApiError) || error.retryable) && (
            <button className="text-button" onClick={onRetry}>Try again <Icon name="arrow" size={14} /></button>
          )}
        </div>
      </section>
    );
  }

  const label = hourLabel(start, hour);
  return (
    <section className="heatmap-panel" aria-label="Corridor forecast">
      <div className="heatmap-header">
        <div className="heatmap-heading"><span className="heatmap-heading-icon"><Icon name="weather" size={20} /></span><div><span className="heatmap-eyebrow">THE CONDITIONS AHEAD</span><h2>48-hour corridor forecast</h2></div></div>
        <div className="heatmap-layers" role="radiogroup" aria-label="Heatmap layer">
          {LAYERS.map((item) => (
            <label key={item.key} className={item.key === layer ? 'is-active' : undefined}>
              <input type="radio" name="heatmap-layer" value={item.key} checked={item.key === layer} onChange={() => setLayer(item.key)} />
              {item.label}
            </label>
          ))}
        </div>
      </div>
      <div className="heatmap-timeline">
        <button
          type="button"
          className="heatmap-play"
          aria-label={playing ? 'Pause forecast' : 'Play forecast'}
          onClick={() => {
            if (!playing && hour >= LAST_HOUR) setHour(0);
            setPlaying(!playing);
          }}
        >
          <Icon name={playing ? 'pause' : 'play'} size={18} />
        </button>
        <div className="heatmap-scrubber">
          <input
            type="range"
            min={0}
            max={LAST_HOUR}
            step={1}
            value={hour}
            aria-label="Forecast hour"
            aria-valuetext={`${label.time}, ${label.date}, ${hour} hours after departure`}
            style={{ backgroundImage: `linear-gradient(to right, var(--forest) ${hour / LAST_HOUR * 100}%, var(--line) ${hour / LAST_HOUR * 100}%)` }}
            onChange={(event) => setHour(Number(event.target.value))}
          />
          <div className="heatmap-ticks" aria-hidden="true"><span>Departure</span><span>+12h</span><span>+24h</span><span>+36h</span><span>+48h</span></div>
        </div>
        <p className="heatmap-time" aria-live="polite">
          <strong>{label.time}</strong> <span>{label.date}</span> <span className="heatmap-offset">+{hour} h</span>
        </p>
      </div>
      {layer === 'risk'
        ? <p className="heatmap-note">Risk reflects your load. Hour 0 is departure.<span className="heatmap-marker-note"> Markers show where each truck would be.</span></p>
        : <ValueScaleKey layer={layer} />}
    </section>
  );
}
