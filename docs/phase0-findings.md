# Phase 0: provider validation

Run on 2026-11-24 with a free-tier TomTom key (no card) and keyless Open-Meteo. Reproduce from `backend/` with
`uv run python scripts/provider_smoke.py .env smoke-results.json` (about 10 TomTom and 4 Open-Meteo requests).

## Verdict

| Check | Result |
|---|---|
| TomTom truck routing on the free tier | **Works.** `travelMode=truck`, `vehicleWeight`, `vehicleCommercial`, `departAt` and `maxAlternatives=2` all accepted. The car/65 mph fallback is **not needed**. |
| Three distinct routes per request | **Not guaranteed.** 2 of 3 test trips returned 3 routes; Dallas → Denver returned 2. The fewer-than-three fallback (spec §5) is required. |
| TomTom Geocoding (`/search/2/geocode`) | Works, about 0.2 s, `countrySet=US` restricts to US. |
| Open-Meteo multi-location, 5 variables, UTC, bounded hours | Works as specified. |
| Open-Meteo forecast horizon | 16 days (today + 15). The 7-day departure limit plus a 48 h heatmap fits comfortably. |

## TomTom routing

| Trip (truck, 42,000 lb = 19,051 kg) | Routes | Distance (mi) | Duration (h) | Max pairwise overlap | Latency |
|---|---|---|---|---|---|
| Dallas → Denver | **2** | 882.4 / 797.0 | 12.2 / 12.7 | 0.9% | 7.98 s (first call) |
| Chicago → Atlanta | 3 | 725 / 757 / 805 | 10.8 / 11.4 / 12.4 | 36% | 4.16 s |
| LA → Phoenix | 3 | 374 / 466 / 513 | 6.0 / 7.8 / 8.6 | 10% | 4.00 s |
| Dallas → Denver, car, `vehicleMaxSpeed=105` | 3 | 787 / 851 / 850 | 12.7 / 13.7 / 14.0 | 22% | 3.48 s |
| Dallas → Denver, truck, via (37.6, -97.3) | 3 | 885 / 1100 / 976 | 12.4 / 16.4 / 15.9 | 19% | 5.20 s |

Overlap here is a rough share of points shared after rounding to 0.01°, not the final overlap metric.

### Findings that affect the spec or plan

1. **Spec §5 fallback step 1 cannot work as written.** `minDeviationDistance` / `minDeviationTime` are rejected in GET requests
   (`400 BAD_INPUT: ... not allowed in GET requests`). The documentation says they apply only when *reconstructing* a supplied
   route (POST with `supportingPoints`). They also do the opposite of what we want: they force alternatives to *follow* the
   reference route for at least that distance or time. Proposal: drop step 1 and go straight to the perpendicular via-point step,
   which was validated above. TomTom returned 3 routes through the via point.
2. **Per-point travel times are available.** With `extendedRouteRepresentation=distance&extendedRouteRepresentation=travelTime`, each
   route has a `progress` array (about 60–280 entries per route, sparse over 4,500–14,500 points) holding cumulative `travelTimeInSeconds`
   and `distanceInMeters` keyed by `pointIndex`. Per spec §6.1, checkpoint ETAs should interpolate within `progress` rather than
   scale the whole route proportionally. Proportional interpolation stays as the fallback if `progress` is missing.
3. **Truck speeds look high.** The primary Dallas → Denver truck route averages 72.3 mph (882 mi in 12.2 h), even though no speed cap was
   sent. Because ETAs determine which forecast hour each checkpoint uses, consider sending `vehicleMaxSpeed` for trucks as well. For example,
   105 km/h (65 mph) matches the car fallback. This is a decision, not yet applied.
4. **Latency.** Routing took 3.5–8.0 s, against the spec's 8 s provider timeout and the 5 s plan-response target for a 1,000 mile trip.
   Routing alone can use most of that budget. The 30-minute route cache helps only on repeat trips. Measure again in phase 6. If the first call
   regularly approaches 8 s, raise the routing timeout to about 15 s and document it.
5. **`TRAVEL_MODE: other` sections.** On Dallas → Denver, short sections at the start and end are tagged `travelMode: other`. That means truck
   routing was not possible there, typically on local streets near a city-centre point. Worth a note in the README. No action needed.
6. **Response shape.** `routes[].summary` has `lengthInMeters`, `travelTimeInSeconds`, `departureTime` and `arrivalTime` (local
   offsets, for example `-06:00` → `-07:00`), plus traffic fields. `routes[].legs[].points` gives full-resolution `{latitude, longitude}`; with a
   via point there is one leg per stop. No encoded polyline is returned, so the backend must encode `geometry` itself.
   Simplifying the polyline before sending it to the client is worth considering, at 10k+ points per route.

### Geocoding

- `Dallas, TX` returned two identical `Dallas, TX` labels (municipality and subdivision). Deduplicate by label in phase 3.
- `Toronto` with `countrySet=US` returns Toronto, KS / OH / IA. The US-only restriction works.
- Point addresses resolve (`1600 Pennsylvania Avenue Northwest, Washington, DC 20500`).

## Open-Meteo

- A comma-separated multi-location request returns a **JSON list**, one object per location in request order.
- `timezone=GMT` gives naive `YYYY-MM-DDTHH:MM` stamps that are UTC hours. Parse them as UTC.
- Units are confirmed: `mp/h` for wind and gusts, `inch` for rain, showers and snowfall.
- `start_hour` / `end_hour` bound the window. 0–48 h inclusive gave exactly 49 hourly rows.
- Returned coordinates are the model grid cell (for example, a request for 32.8, -96.8 returns 32.81, -96.80), not the requested point. Key the
  cache on our requested 0.1° lattice cell, not on the echoed coordinates.
- No nulls in the 48 h sample. Missing-data handling still has to be implemented and tested (spec §6.2).
- Out-of-range windows fail with `400` and a readable reason (`start_hour is out of allowed range from ... to 2026-12-09`).

## Terms (read 2026-11-24)

- **Open-Meteo:** the free API is "only for non-commercial purposes". Examples given are non-profit or private apps without
  subscriptions or ads, and educational use. A hiring assessment and portfolio demo with no ads or subscriptions fits that reading, but it is not
  named explicitly, so the README should state it. The limits are 600 calls per minute, 5,000 per hour, 10,000 per day and 300,000 per month, enforced
  per IP. More than 10 variables or more than 2 weeks counts as multiple calls. The pricing page **does not document how multi-location
  requests are counted**. Keep the spec's conservative assumption that each location counts as one call. Data licence: CC BY 4.0
  (attribution "Weather data by Open-Meteo.com" is already in the map footer).
- **TomTom:** 20K free requests per month each for the Routing API and the Geocoding API, with no card needed. The old fuzzy Search API allows only 2.5K, as
  spec §5 says. The pricing page does not mention travel mode. Truck mode worked in practice on the free key.

## Still open

- The five Spotter questions (spec §15) have not been sent or answered. The documented assumptions stay in place.

## Decisions (2026-11-24)

- Fallback step 1 (spec §5): **spec left unchanged**; revisit in phase 6 with the GET restriction above in mind.
- Truck speed: **no cap**; TomTom's truck speed profile is used as returned.
- Provider timeout: **8 s everywhere** as specified; re-measure routing latency in phase 6.
