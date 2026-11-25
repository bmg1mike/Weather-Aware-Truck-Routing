"""End-to-end scenarios from plan phase 6, through the real views with fake providers.

Each test names one scenario a driver can hit. Lower-level tests cover the mechanics; these show
the API answer for the whole situation.
"""

from datetime import timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.errors import ProviderRateLimited, ProviderUnavailable
from trips.services.planner import TripPlanner
from trips.services.weather import HourValues, WeatherLookup
from trips.tests.helpers import iso_in
from trips.tests.test_planner import (
    CALM,
    FakeRouting,
    FakeWeather,
    ViaRouting,
    by_side,
    north_route,
)


@pytest.fixture
def serve(monkeypatch, request):
    """Serve plans from ``routing`` and hourly weather from ``conditions(cell, hour)``."""

    def install(routing, conditions=lambda c, h: CALM, missing=()):
        weather = FakeWeather(conditions, missing)
        lookup = WeatherLookup(weather, LocMemCache(request.node.nodeid, {}))
        monkeypatch.setattr("trips.api.views.get_planner", lambda: TripPlanner(routing, lookup))
        return weather

    return install


def plan(client, payload, **overrides):
    response = client.post("/api/trips/plan", {**payload, **overrides}, format="json")
    return response.status_code, response.json()


def test_no_safe_route_recommends_the_least_bad_and_names_the_stretch(client, plan_payload, serve):
    def storm_on_a(cell, hour):
        return (
            HourValues(60.0, 70.0, 0, 0, 0) if cell.lon == -100.0 else HourValues(56.0, 60, 0, 0, 0)
        )

    routes = [north_route("r1", 100, 2), north_route("r2", 100, 2, lon=-101)]
    serve(FakeRouting(routes), storm_on_a)
    status, body = plan(client, plan_payload)
    assert status == 200 and body["no_safe_route"] is True
    best = body["routes"][0]
    assert best["reason"].startswith("Least bad:")
    assert best["summary"]["no_travel_stretches"]


def test_forecast_gap_is_reported_not_scored_as_low(client, plan_payload, serve):
    from trips.domain import LatLon

    serve(FakeRouting([north_route("r1", 100, 2)]), missing=[LatLon(35.4, -100.0)])
    status, body = plan(client, plan_payload)
    summary = body["routes"][0]["summary"]
    assert status == 200
    assert summary["unknown_checkpoints"] == 1 and summary["unknown_mi"] == 50.0
    assert summary["miles_by_level"]["low"] == 50.0
    assert [cp["level"] for cp in body["routes"][0]["checkpoints"]].count("unknown") == 1


@pytest.mark.parametrize(
    "departure",
    [
        "2026-11-25T06:00:00",
        "25/11/2026 06:00",
        iso_in(-timedelta(hours=1)),
        iso_in(timedelta(days=8)),
    ],
    ids=["no-offset", "not-iso", "past", "beyond-7-days"],
)
def test_invalid_departure_is_rejected_before_any_provider_call(
    client, plan_payload, serve, departure
):
    routing = FakeRouting([north_route("r1", 100, 2)])
    serve(routing)
    status, body = plan(client, plan_payload, departure=departure)
    assert status == 400 and body["error"]["message"].startswith("departure:")
    assert routing.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderUnavailable("TomTom"), 502, "provider_unavailable"),
        (ProviderRateLimited("TomTom", 30), 503, "provider_rate_limited"),
    ],
    ids=["timeout", "429"],
)
def test_provider_failure_is_readable_and_retryable(
    client, plan_payload, serve, error, status, code
):
    class Failing:
        def routes(self, *args, **kwargs):
            raise error

    serve(Failing())
    response = client.post("/api/trips/plan", plan_payload, format="json")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    if status == 503:
        assert response["Retry-After"] == "30"


def test_long_trip_fits_the_budget_at_ten_miles(client, plan_payload, serve):
    routes = [north_route(f"r{i}", 1000, 15, lon=-100 - i) for i in range(1, 4)]
    weather = serve(FakeRouting(routes))
    status, body = plan(client, plan_payload, interval_mi=10)
    assert status == 200
    cells = len(set(weather.requested_cells))
    assert cells + body["corridor"]["max_grid_points"] <= 500


def test_trip_too_long_for_the_budget_asks_for_a_larger_interval(client, plan_payload, serve):
    routes = [north_route(f"r{i}", 1500, 22, lon=-100 - i) for i in range(1, 4)]
    weather = serve(FakeRouting(routes))
    status, body = plan(client, plan_payload, interval_mi=10)
    assert status == 422 and body["error"]["code"] == "budget_exceeded"
    assert "25 or 50 mile" in body["error"]["message"]
    assert weather.requested_cells == []
    assert plan(client, plan_payload, interval_mi=50)[0] == 200


def test_heavy_load_escalates_wind_risk_end_to_end(client, plan_payload, serve):
    def high_wind(cell, hour):
        return HourValues(40.0, 50.0, 0, 0, 0)

    serve(FakeRouting([north_route("r1", 100, 2)]), high_wind)
    light = plan(client, plan_payload, load_lb=40_000)[1]["routes"][0]["checkpoints"][0]["level"]
    heavy = plan(client, plan_payload, load_lb=40_001)[1]["routes"][0]["checkpoints"][0]["level"]
    assert (light, heavy) == ("high", "severe")


def test_duplicate_routes_collapse_and_report_fewer_routes(client, plan_payload, serve):
    same_road = [north_route("r1", 100, 2), north_route("r2", 100, 2.05, lon=-100.002)]
    serve(ViaRouting(same_road))  # via requests find nothing distinct
    status, body = plan(client, plan_payload)
    assert status == 200
    assert [r["id"] for r in body["routes"]] == ["r1"]


def test_fewer_than_three_routes_are_topped_up_through_via_points(client, plan_payload, serve):
    routing = ViaRouting(
        [north_route("r1", 100, 2)],
        by_side(
            west=north_route("x", 110, 2.2, lon=-100.8), east=north_route("x", 112, 2.3, lon=-99.2)
        ),
    )
    serve(routing)
    status, body = plan(client, plan_payload)
    assert status == 200
    assert [r["name"] for r in sorted(body["routes"], key=lambda r: r["id"])] == [
        "Route A",
        "Route B",
        "Route C",
    ]
