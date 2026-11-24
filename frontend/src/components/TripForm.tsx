import { useQuery } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Place, PlanRequest, SamplingInterval } from '../api/types';
import { Icon } from './Icon';

interface LocationInput {
  text: string;
  place: Place | null;
}

function PlaceInput({
  label,
  value,
  onChange,
  destination = false,
  error,
}: {
  label: string;
  value: LocationInput;
  onChange: (value: LocationInput) => void;
  destination?: boolean;
  error?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [debounced, setDebounced] = useState('');
  const search = value.text.trim();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const suggestions = useQuery({
    queryKey: ['geocode', debounced],
    queryFn: ({ signal }) => api.geocode(debounced, signal),
    enabled: open && !value.place && search.length >= 3 && search === debounced,
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  });
  const visible = open && !value.place && search.length >= 3 && search === debounced;
  const places = visible ? (suggestions.data?.results ?? []) : [];
  const expanded = visible && places.length > 0;

  function choose(place: Place) {
    onChange({ text: place.label, place });
    setOpen(false);
    setActive(-1);
  }

  return (
    <div
      className={`place-field ${destination ? 'place-field--destination' : ''}`}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <span className="place-marker" aria-hidden="true" />
      <div className="place-field-body">
        <label htmlFor={id}>{label}</label>
        <input
          id={id}
          role="combobox"
          autoComplete="off"
          placeholder={destination ? 'Where are you headed?' : 'City or street address'}
          value={value.text}
          aria-expanded={expanded}
          aria-autocomplete="list"
          aria-invalid={Boolean(error)}
          aria-controls={`${id}-suggestions`}
          aria-activedescendant={expanded && active >= 0 ? `${id}-option-${active}` : undefined}
          aria-describedby={[error ? `${id}-error` : '', visible && (suggestions.error || suggestions.isFetching) ? `${id}-status` : ''].filter(Boolean).join(' ') || undefined}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            onChange({ text: event.target.value, place: null });
            setOpen(true);
            setActive(-1);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false);
              setActive(-1);
            } else if (!open && !value.place && search.length >= 3 && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
              event.preventDefault();
              setOpen(true);
              setActive(event.key === 'ArrowUp' ? (suggestions.data?.results.length ?? 0) - 1 : 0);
            } else if (places.length > 0 && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
              event.preventDefault();
              setActive((current) =>
                event.key === 'ArrowDown'
                  ? (current + 1) % places.length
                  : (current <= 0 ? places.length : current) - 1,
              );
            } else if (event.key === 'Enter' && expanded && active >= 0) {
              event.preventDefault();
              const place = places[active];
              if (place) choose(place);
            }
          }}
        />
        {error && <p className="field-error" id={`${id}-error`} role="alert">{error}</p>}
      </div>
      {expanded && (
        <ul className="place-suggestions" id={`${id}-suggestions`} role="listbox" aria-label={`${label} suggestions`}>
          {places.map((place, index) => (
            <li
              key={`${place.lat},${place.lon},${place.label}`}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={active === index}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(place)}
            >
              <Icon name="location" size={16} />
              {place.label}
            </li>
          ))}
        </ul>
      )}
      {visible && (
        <div id={`${id}-status`} className="place-status" role="status">
          {suggestions.isFetching ? 'Finding places…' : suggestions.error ? (
            <>
              {suggestions.error.message}
              {suggestions.error instanceof ApiError && suggestions.error.retryable && (
                <button type="button" className="text-button" onClick={() => void suggestions.refetch()}>Try again</button>
              )}
            </>
          ) : suggestions.isSuccess && places.length === 0 ? 'No places found. Try a more specific US address.' : null}
        </div>
      )}
    </div>
  );
}

function initialDeparture(): string {
  const date = new Date();
  date.setHours(date.getHours() + 1, 0, 0, 0);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function TripForm({
  onSubmit,
  pending,
}: {
  onSubmit: (request: PlanRequest) => void;
  pending: boolean;
}) {
  const [origin, setOrigin] = useState<LocationInput>({ text: '', place: null });
  const [destination, setDestination] = useState<LocationInput>({ text: '', place: null });
  const [departure, setDeparture] = useState(initialDeparture);
  const [load, setLoad] = useState('40000');
  const [interval, setInterval] = useState<SamplingInterval>(25);
  const [validation, setValidation] = useState<{ field: 'origin' | 'destination' | 'departure' | 'load'; message: string } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (validation) formRef.current?.querySelector<HTMLInputElement>('[aria-invalid="true"]')?.focus();
  }, [validation]);

  return (
    <form
      className="trip-form"
      ref={formRef}
      aria-label="Trip details"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const time = new Date(departure).getTime();
        const weight = Number(load);
        const now = Date.now();
        let error: typeof validation = null;
        if (!origin.place) {
          error = { field: 'origin', message: 'Choose an origin from the address suggestions.' };
        } else if (!destination.place) {
          error = { field: 'destination', message: 'Choose a destination from the address suggestions.' };
        } else if (origin.place.lat === destination.place.lat && origin.place.lon === destination.place.lon) {
          error = { field: 'destination', message: 'Your origin and destination must be different.' };
        } else if (!Number.isFinite(time) || time < now - 5 * 60_000 || time > now + 7 * 24 * 60 * 60_000) {
          error = { field: 'departure', message: 'Choose a departure between now and seven days from now.' };
        } else if (!Number.isInteger(weight) || weight < 1 || weight > 80_000) {
          error = { field: 'load', message: 'Enter a whole-number load weight between 1 and 80,000 lb.' };
        }
        setValidation(error);
        if (error || !origin.place || !destination.place) return;
        onSubmit({
          origin: origin.place,
          destination: destination.place,
          departure: new Date(time).toISOString(),
          load_lb: weight,
          interval_mi: interval,
        });
      }}
    >
      <fieldset disabled={pending} className="form-fields">
        <legend className="sr-only">Your trip</legend>
        <div className="locations">
          <PlaceInput label="Origin" value={origin} error={validation?.field === 'origin' ? validation.message : undefined} onChange={(value) => { setOrigin(value); if (validation?.field === 'origin') setValidation(null); }} />
          <button
            type="button"
            className="swap-button"
            aria-label="Swap origin and destination"
            onClick={() => {
              setOrigin(destination);
              setDestination(origin);
              setValidation(null);
            }}
          >
            <Icon name="swap" size={16} />
          </button>
          <PlaceInput label="Destination" value={destination} error={validation?.field === 'destination' ? validation.message : undefined} onChange={(value) => { setDestination(value); if (validation?.field === 'destination') setValidation(null); }} destination />
        </div>

        <div className="form-section-label"><span>Departure & vehicle</span><span className="section-rule" /></div>
        <label className="input-label" htmlFor="departure">Departure time <span>Local time</span></label>
        <input
          id="departure"
          className="form-input"
          type="datetime-local"
          value={departure}
          aria-invalid={validation?.field === 'departure'}
          aria-describedby={validation?.field === 'departure' ? 'departure-error departure-help' : 'departure-help'}
          onChange={(event) => { setDeparture(event.target.value); if (validation?.field === 'departure') setValidation(null); }}
        />
        <p className="field-help" id="departure-help">Your time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Up to 7 days ahead.</p>
        {validation?.field === 'departure' && <p className="field-error" id="departure-error" role="alert">{validation.message}</p>}
        <div className="load-heading">
          <label className="input-label" htmlFor="load">Load weight</label>
          <span className="field-note">Up to 80,000 lb</span>
        </div>
        <div className="input-with-unit">
          <Icon name="truck" size={18} />
          <input id="load" type="number" min="1" max="80000" step="1" value={load} aria-invalid={validation?.field === 'load'} aria-describedby={validation?.field === 'load' ? 'load-error' : undefined} onChange={(event) => { setLoad(event.target.value); if (validation?.field === 'load') setValidation(null); }} />
          <span>lb</span>
        </div>
        {validation?.field === 'load' && <p className="field-error" id="load-error" role="alert">{validation.message}</p>}

        <fieldset className="sampling-field">
          <legend className="input-label">Weather checkpoint interval</legend>
          <div className="segmented-control">
            {([10, 25, 50] as const).map((miles) => (
              <label key={miles}>
                <input type="radio" name="interval" aria-label={`${miles} miles`} value={miles} checked={interval === miles} onChange={() => setInterval(miles)} />
                <span>{miles}<small> mi</small>{miles === 25 && <span className="recommended-dot" aria-hidden="true" />}</span>
              </label>
            ))}
          </div>
          <p className="field-help">Closer checkpoints. A more detailed picture.</p>
        </fieldset>
        <button className="primary-button" type="submit">
          {pending ? <><span className="spinner" /> Comparing routes…</> : <>Find my route <Icon name="arrow" size={19} /></>}
        </button>
      </fieldset>
      <p className="form-footnote"><Icon name="shield" size={13} /> Weather-aware. Road-ready.</p>
    </form>
  );
}
