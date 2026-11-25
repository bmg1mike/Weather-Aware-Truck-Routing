"""Trip planning: routes → checkpoints → weather at each ETA → risk → summary → ranking."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime

from trips.domain import (
    SAMPLING_INTERVALS_MI,
    Checkpoint,
    LatLon,
    Place,
    RouteOption,
    SamplingInterval,
)
from trips.errors import BudgetExceeded, NoRouteFound, ProviderRateLimited, ProviderUnavailable
from trips.services.geometry import in_us, overlap_fraction, perpendicular_via_points
from trips.services.risk import classify
from trips.services.routing import RoutingProvider
from trips.services.sampling import sample_checkpoints
from trips.services.scoring import (
    RouteScore,
    RouteSummary,
    no_travel_stretches,
    rank_routes,
    segments,
    summarize,
)
from trips.services.weather import (
    HourValues,
    WeatherLookup,
    checkpoint_weather,
    hours_needed,
    snap_to_lattice,
)

logger = logging.getLogger(__name__)

# Free-tier budget (spec section 5): at most 500 unique weather locations per trip, checkpoints plus
# heatmap grid. The heatmap takes what checkpoints leave (at most 200, widening its spacing to fit);
# checkpoints may use up to 400 so the heatmap always keeps at least 100.
MAX_TRIP_LOCATIONS = 500
HEATMAP_MAX_POINTS = 200
HEATMAP_MIN_POINTS = 100
MAX_CHECKPOINT_CELLS = MAX_TRIP_LOCATIONS - HEATMAP_MIN_POINTS
CORRIDOR_BUFFER_MI = 30
MAX_ROUTES = 3
MAX_OVERLAP = 0.80  # a route sharing more than this share of its length with another is a duplicate
# Via points sit ~10% of the trip length off the primary midpoint (spec section 5). At 10% a detour
# often rejoins the primary road (measured: 80-81% overlap on Dallas-Denver), so one wider round
# at 20% follows if routes are still short.
VIA_OFFSET_FRACTIONS = (0.10, 0.20)
MAX_DETOUR_RATIO = 1.5  # a via route taking 50% longer than the primary is not a useful option
_MI_PER_DEG_LAT = 69.0
_ROUTE_NAMES = "ABCDEFGHIJ"


@dataclass(frozen=True, slots=True)
class PlanInput:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: int
    interval_mi: SamplingInterval


@dataclass(frozen=True, slots=True)
class PlannedRoute:
    option: RouteOption
    name: str
    rank: int
    reason: str
    checkpoints: list[Checkpoint]
    summary: RouteSummary
    no_travel_stretches: list[tuple[float, float]]

    @property
    def id(self) -> str:
        return self.option.id


@dataclass(frozen=True, slots=True)
class TripPlan:
    routes: list[PlannedRoute]
    """Best first."""
    recommended_id: str
    no_safe_route: bool
    bbox: tuple[float, float, float, float]
    """Corridor [min_lon, min_lat, max_lon, max_lat] around all routes."""
    max_grid_points: int
    """Weather locations left for the heatmap so the trip stays within 500 in total."""


def corridor_bbox(
    routes: Sequence[RouteOption], buffer_mi: float = CORRIDOR_BUFFER_MI
) -> tuple[float, float, float, float]:
    lats = [p.lat for r in routes for p in r.points]
    lons = [p.lon for r in routes for p in r.points]
    lat_pad = buffer_mi / _MI_PER_DEG_LAT
    widest_lat = max(abs(min(lats)), abs(max(lats)))
    lon_pad = buffer_mi / (_MI_PER_DEG_LAT * max(math.cos(math.radians(widest_lat)), 0.1))
    return (
        max(min(lons) - lon_pad, -180.0),
        max(min(lats) - lat_pad, -90.0),
        min(max(lons) + lon_pad, 180.0),
        min(max(lats) + lat_pad, 90.0),
    )


def _budget_message(cells: int, limit: int, interval: int) -> str:
    larger = [str(i) for i in SAMPLING_INTERVALS_MI if i > interval]
    advice = f"Choose a {' or '.join(larger)} mile interval." if larger else "Try a shorter trip."
    return (
        f"This trip needs {cells} weather locations at a {interval} mile interval, "
        f"over the free-tier limit of {limit}. {advice}"
    )


def _keep_distinct(
    kept: Sequence[RouteOption], candidates: Sequence[RouteOption]
) -> list[RouteOption]:
    result = list(kept)
    for candidate in candidates:
        if len(result) >= MAX_ROUTES:
            break
        if all(overlap_fraction(candidate.points, other.points) <= MAX_OVERLAP for other in result):
            result.append(candidate)
    return result


class TripPlanner:
    def __init__(
        self,
        routing: RoutingProvider,
        weather: WeatherLookup,
        *,
        wind_source: str = "sustained",
        max_checkpoint_cells: int = MAX_CHECKPOINT_CELLS,
    ) -> None:
        self.routing = routing
        self.weather = weather
        self.wind_source = wind_source
        self.max_checkpoint_cells = max_checkpoint_cells

    def plan(self, trip: PlanInput) -> TripPlan:
        options = self._distinct_routes(trip)
        sampled = {option.id: sample_checkpoints(option, trip.interval_mi) for option in options}

        needs: dict[LatLon, set[datetime]] = {}
        for checkpoints in sampled.values():
            for cp in checkpoints:
                needs.setdefault(snap_to_lattice(cp.point), set()).update(hours_needed(cp.eta))
        if len(needs) > self.max_checkpoint_cells:
            raise BudgetExceeded(
                _budget_message(len(needs), self.max_checkpoint_cells, trip.interval_mi)
            )

        values = self.weather.values(needs)
        classified = {
            route_id: [self._classify(cp, values, trip.load_lb) for cp in checkpoints]
            for route_id, checkpoints in sampled.items()
        }
        names = {option.id: f"Route {_ROUTE_NAMES[i]}" for i, option in enumerate(options)}
        summaries = {route_id: summarize(cps) for route_id, cps in classified.items()}
        ranking = rank_routes(
            [
                RouteScore(
                    id=option.id,
                    name=names[option.id],
                    duration_s=option.duration_s,
                    summary=summaries[option.id],
                )
                for option in options
            ]
        )
        by_id = {option.id: option for option in options}
        planned = [
            PlannedRoute(
                option=by_id[ranked.route.id],
                name=ranked.route.name,
                rank=ranked.rank,
                reason=ranked.reason,
                checkpoints=classified[ranked.route.id],
                summary=ranked.route.summary,
                no_travel_stretches=no_travel_stretches(segments(classified[ranked.route.id])),
            )
            for ranked in ranking.routes
        ]
        return TripPlan(
            routes=planned,
            recommended_id=ranking.recommended.route.id,
            no_safe_route=ranking.no_safe_route,
            bbox=corridor_bbox(options),
            max_grid_points=min(HEATMAP_MAX_POINTS, MAX_TRIP_LOCATIONS - len(needs)),
        )

    def _distinct_routes(self, trip: PlanInput) -> list[RouteOption]:
        """Up to three routes, none overlapping a kept one by more than 80% (spec section 5).

        If TomTom returns fewer, routes through via points left and right of the primary route's
        midpoint are requested in parallel. The spec's first step (relaxed deviation settings) is
        skipped: TomTom accepts those parameters only when reconstructing a supplied route, and
        that returned no extra route in testing (docs/phase0-findings.md).
        """
        kept = _keep_distinct(
            [],
            self.routing.routes(
                trip.origin.point,
                trip.destination.point,
                departure=trip.departure,
                load_lb=trip.load_lb,
            ),
        )
        for fraction in VIA_OFFSET_FRACTIONS:
            if not 0 < len(kept) < MAX_ROUTES:
                break
            primary = kept[0]
            detours = [
                route
                for route in self._via_routes(trip, primary, fraction)
                if route.duration_s <= primary.duration_s * MAX_DETOUR_RATIO
            ]
            kept = _keep_distinct(kept, detours)
        return [replace(option, id=f"r{i}") for i, option in enumerate(kept[:MAX_ROUTES], start=1)]

    def _via_routes(
        self, trip: PlanInput, primary: RouteOption, fraction: float
    ) -> list[RouteOption]:
        offset = primary.distance_mi * fraction
        vias = [v for v in perpendicular_via_points(primary.points, offset) if in_us(v.lat, v.lon)]

        def request(via: LatLon) -> list[RouteOption]:
            try:
                routes = self.routing.routes(
                    trip.origin.point,
                    trip.destination.point,
                    departure=trip.departure,
                    load_lb=trip.load_lb,
                    max_alternatives=0,
                    via=[via],
                )
            except (NoRouteFound, ProviderUnavailable, ProviderRateLimited) as exc:
                logger.info("Via-point route unavailable (%s); continuing without it.", exc.code)
                return []
            return routes[:1]

        if not vias:
            return []
        with ThreadPoolExecutor(max_workers=len(vias)) as pool:
            return [route for routes in pool.map(request, vias) for route in routes]

    def _classify(
        self,
        checkpoint: Checkpoint,
        values: Mapping[tuple[LatLon, datetime], HourValues],
        load_lb: int,
    ) -> Checkpoint:
        weather = checkpoint_weather(checkpoint.eta, snap_to_lattice(checkpoint.point), values)
        if weather is None:
            return checkpoint
        scored_wind = weather.gust_mph if self.wind_source == "gust" else weather.wind_mph
        if scored_wind is None:
            return replace(checkpoint, weather=weather)  # no gust forecast: cannot score
        level, driver = classify(scored_wind, weather.rain_in_hr, weather.snow_in_hr, load_lb)
        return replace(checkpoint, weather=weather, level=level, driver=driver)
