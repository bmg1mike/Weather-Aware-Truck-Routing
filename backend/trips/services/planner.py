"""Trip planning: routes → checkpoints → weather at each ETA → risk → summary → ranking."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
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
from trips.errors import BudgetExceeded
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

# Free-tier budget (spec section 5): at most 500 unique weather locations per trip, of which up to
# 200 are reserved for the heatmap grid, leaving 300 for checkpoints.
MAX_TRIP_LOCATIONS = 500
HEATMAP_MAX_POINTS = 200
MAX_CHECKPOINT_CELLS = MAX_TRIP_LOCATIONS - HEATMAP_MAX_POINTS
CORRIDOR_BUFFER_MI = 30
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
        options = self.routing.routes(
            trip.origin.point,
            trip.destination.point,
            departure=trip.departure,
            load_lb=trip.load_lb,
        )
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
        )

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
