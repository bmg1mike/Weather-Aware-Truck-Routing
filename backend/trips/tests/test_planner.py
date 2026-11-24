"""Trip planning orchestration with fake routing and weather providers."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.domain import HourlyForecast, LatLon, Place, RiskLevel, RouteOption
from trips.errors import BudgetExceeded
from trips.services.planner import PlanInput, TripPlanner
from trips.services.sampling import haversine_mi
from trips.services.weather import HourValues, WeatherLookup

DEPART = datetime(2026, 11, 25, 12, tzinfo=UTC)
MI_PER_DEG_LAT = haversine_mi(LatLon(0, 0), LatLon(1, 0))
CALM = HourValues(5.0, 10.0, 0.0, 0.0, 0.0)


def north_route(route_id: str, miles: float, hours: float, lon: float = -100.0) -> RouteOption:
    span = miles / MI_PER_DEG_LAT
    points = tuple(LatLon(35 + span * i / 100, lon) for i in range(101))
    return RouteOption(
        id=route_id,
        points=points,
        distance_mi=miles,
        duration_s=round(hours * 3600),
        departure=DEPART,
        arrival=DEPART + timedelta(hours=hours),
    )


class FakeRouting:
    def __init__(self, routes):
        self.routes_to_return = routes
        self.calls = []

    def routes(self, origin, destination, **kwargs):
        self.calls.append((origin, destination, kwargs))
        return self.routes_to_return


class FakeWeather:
    """Hourly values from ``conditions(cell, hour)``; cells in ``missing`` are not returned."""

    def __init__(self, conditions: Callable[[LatLon, datetime], HourValues], missing=()):
        self.conditions = conditions
        self.missing = set(missing)
        self.requested_cells: list[LatLon] = []

    def hourly(self, cells, *, start, end):
        self.requested_cells.extend(cells)
        hours = [
            start + timedelta(hours=i) for i in range(int((end - start) / timedelta(hours=1)) + 1)
        ]
        result = {}
        for cell in cells:
            if cell in self.missing:
                continue
            values = [self.conditions(cell, h) for h in hours]
            result[cell] = HourlyForecast(
                cell=cell,
                times=tuple(hours),
                wind_mph=tuple(v.wind_mph for v in values),
                gust_mph=tuple(v.gust_mph for v in values),
                rain_in=tuple(v.rain_in for v in values),
                showers_in=tuple(v.showers_in for v in values),
                snow_in=tuple(v.snow_in for v in values),
            )
        return result


def planner(routes, conditions=lambda c, h: CALM, *, missing=(), cache_name, **kwargs):
    weather = FakeWeather(conditions, missing)
    lookup = WeatherLookup(weather, LocMemCache(cache_name, {}))
    return TripPlanner(FakeRouting(routes), lookup, **kwargs), weather


def plan_input(interval=25, load=20_000) -> PlanInput:
    return PlanInput(
        origin=Place("Origin", LatLon(35, -100)),
        destination=Place("Destination", LatLon(36.5, -100)),
        departure=DEPART,
        load_lb=load,
        interval_mi=interval,
    )


@pytest.fixture
def name(request):
    return request.node.nodeid


def test_passes_trip_details_to_routing(name):
    trip, _ = planner([north_route("r1", 100, 2)], cache_name=name)
    trip.plan(plan_input(load=42_000))
    origin, destination, kwargs = trip.routing.calls[0]
    assert (origin, destination) == (LatLon(35, -100), LatLon(36.5, -100))
    assert kwargs["departure"] == DEPART and kwargs["load_lb"] == 42_000


def test_routes_are_ranked_and_named_in_provider_order(name):
    stormy_lon = -101.0

    def conditions(cell, hour):
        return HourValues(48.0, 60.0, 0, 0, 0) if cell.lon == stormy_lon else CALM

    routes = [north_route("r1", 100, 2, lon=stormy_lon), north_route("r2", 110, 2.5)]
    result = planner(routes, conditions, cache_name=name)[0].plan(plan_input())
    assert [(r.name, r.rank) for r in result.routes] == [("Route B", 1), ("Route A", 2)]
    assert result.recommended_id == "r2"
    assert result.no_safe_route is False
    assert result.routes[1].summary.miles_by_level[RiskLevel.SEVERE] == pytest.approx(100)
    assert "Severe" in result.routes[0].reason


def test_checkpoints_carry_weather_level_and_driver(name):
    def conditions(cell, hour):
        return HourValues(10.0, 14.0, 0.2, 0.1, 0.0)  # rain 0.3 in/hr is High

    result = planner([north_route("r1", 100, 2)], conditions, cache_name=name)[0].plan(plan_input())
    checkpoint = result.routes[0].checkpoints[1]
    assert checkpoint.mile == pytest.approx(25)
    assert checkpoint.weather is not None and checkpoint.weather.rain_in_hr == pytest.approx(0.3)
    assert (checkpoint.level, checkpoint.driver) == (RiskLevel.HIGH, "rain")


def test_weather_hours_follow_each_checkpoint_eta(name):
    # Wind is calm before 13:00 UTC and 50 mph from 13:00. The 100 mi route takes 2 h, so the
    # checkpoint at mile 25 (12:30, nearest hour 13:00) is already windy.
    def conditions(cell, hour):
        return HourValues(50.0 if hour.hour >= 13 else 5.0, None, 0, 0, 0)

    result = planner([north_route("r1", 100, 2)], conditions, cache_name=name)[0].plan(plan_input())
    levels = [cp.level for cp in result.routes[0].checkpoints]
    assert levels[0] == RiskLevel.LOW
    assert levels[1:] == [RiskLevel.SEVERE] * 4


def test_load_rules_use_the_entered_load(name):
    def conditions(cell, hour):
        return HourValues(40.0, 50.0, 0, 0, 0)

    light = planner([north_route("r1", 50, 1)], conditions, cache_name=name)[0]
    assert light.plan(plan_input(load=40_000)).routes[0].checkpoints[0].level == RiskLevel.HIGH
    heavy = planner([north_route("r1", 50, 1)], conditions, cache_name=name + "h")[0]
    assert heavy.plan(plan_input(load=40_001)).routes[0].checkpoints[0].level == RiskLevel.SEVERE


def test_gust_wind_source_scores_gusts(name):
    def conditions(cell, hour):
        return HourValues(10.0, 50.0, 0, 0, 0)

    trip = planner([north_route("r1", 50, 1)], conditions, cache_name=name, wind_source="gust")[0]
    checkpoint = trip.plan(plan_input()).routes[0].checkpoints[0]
    assert (checkpoint.level, checkpoint.driver) == (RiskLevel.SEVERE, "wind")


def test_missing_forecast_marks_checkpoints_unknown_not_low(name):
    route = north_route("r1", 100, 2)
    missing_cell = LatLon(35.4, -100.0)  # lattice cell of the mile-25 checkpoint
    result = planner([route], missing=[missing_cell], cache_name=name)[0].plan(plan_input())
    planned = result.routes[0]
    assert planned.checkpoints[1].level is None
    assert planned.checkpoints[1].weather is None
    assert planned.summary.unknown_checkpoints == 1
    assert planned.summary.unknown_mi == pytest.approx(50)


def test_overlapping_routes_share_lattice_cells(name):
    routes = [north_route("r1", 100, 2), north_route("r2", 100, 2.2, lon=-100.01)]
    trip, weather = planner(routes, cache_name=name)
    trip.plan(plan_input())
    assert len(weather.requested_cells) == len(set(weather.requested_cells)) == 5


def test_budget_exceeded_suggests_a_larger_interval_before_fetching_weather(name):
    routes = [north_route(f"r{i}", 1000, 15, lon=-100 - i) for i in range(1, 4)]
    trip, weather = planner(routes, cache_name=name, max_checkpoint_cells=250)
    with pytest.raises(BudgetExceeded) as info:
        trip.plan(plan_input(interval=10))
    assert "25 or 50 mile" in info.value.message
    assert weather.requested_cells == []


def test_no_safe_route_reports_the_stretch(name):
    def conditions(cell, hour):
        return HourValues(60.0, 70.0, 0, 0, 0)

    result = planner([north_route("r1", 50, 1)], conditions, cache_name=name)[0].plan(plan_input())
    assert result.no_safe_route is True
    assert result.routes[0].no_travel_stretches == [(0, pytest.approx(50))]


def test_corridor_bbox_covers_every_route_with_a_buffer(name):
    routes = [north_route("r1", 100, 2), north_route("r2", 100, 2, lon=-101)]
    min_lon, min_lat, max_lon, max_lat = planner(routes, cache_name=name)[0].plan(plan_input()).bbox
    assert min_lat < 35 - 0.4 and max_lat > 35 + 100 / MI_PER_DEG_LAT + 0.4
    assert min_lon < -101 - 0.4 and max_lon > -100 + 0.4
