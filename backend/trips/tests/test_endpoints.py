"""Plan and geocode endpoints end to end, with fake providers behind the real views."""

from datetime import timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.domain import LatLon, Place
from trips.errors import ProviderRateLimited, ProviderUnavailable
from trips.services.planner import TripPlanner
from trips.services.sampling import decode_polyline
from trips.services.weather import HourValues, WeatherLookup
from trips.tests.helpers import iso_in
from trips.tests.test_planner import CALM, FakeRouting, FakeWeather, north_route


@pytest.fixture
def use_planner(monkeypatch, request):
    def install(routes, conditions=lambda c, h: CALM, routing=None):
        lookup = WeatherLookup(FakeWeather(conditions), LocMemCache(request.node.nodeid, {}))
        planner = TripPlanner(routing or FakeRouting(routes), lookup)
        monkeypatch.setattr("trips.api.views.get_planner", lambda: planner)
        return planner

    return install


def post_plan(client, payload):
    return client.post("/api/trips/plan", payload, format="json")


def test_plan_response_matches_the_contract(client, plan_payload, use_planner):
    routes = [north_route("r1", 100, 2), north_route("r2", 120, 2.5, lon=-100.5)]
    use_planner(routes)
    response = post_plan(client, plan_payload)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert set(body) == {"recommended_route_id", "no_safe_route", "routes", "corridor"}
    assert body["recommended_route_id"] == "r1"
    assert body["no_safe_route"] is False
    assert len(body["corridor"]["bbox"]) == 4

    route = body["routes"][0]
    assert set(route) == {
        "id",
        "name",
        "rank",
        "reason",
        "distance_mi",
        "duration_s",
        "arrival",
        "geometry",
        "summary",
        "checkpoints",
        "segments",
    }
    assert (route["id"], route["name"], route["rank"]) == ("r1", "Route A", 1)
    assert route["distance_mi"] == 100.0
    assert route["duration_s"] == 7200
    assert route["summary"] == {
        "miles_by_level": {
            "low": 100.0,
            "moderate": 0.0,
            "high": 0.0,
            "severe": 0.0,
            "no_travel": 0.0,
        },
        "unknown_mi": 0.0,
        "avg_risk": 0.0,
        "unknown_checkpoints": 0,
        "no_travel_stretches": [],
    }
    assert len(decode_polyline(route["geometry"])) == 101
    assert len(route["segments"]) == len(route["checkpoints"]) - 1
    for i, segment in enumerate(route["segments"]):
        assert set(segment) == {"start_mi", "end_mi", "geometry", "level"}
        assert segment["level"] == "low"
        assert segment["start_mi"] == route["checkpoints"][i]["mile"]
        assert segment["end_mi"] == route["checkpoints"][i + 1]["mile"]
        points = decode_polyline(segment["geometry"])
        assert len(points) > 2  # retain road vertices, not a straight checkpoint-to-checkpoint line
        assert points[0] == LatLon(route["checkpoints"][i]["lat"], route["checkpoints"][i]["lon"])
        assert points[-1] == LatLon(
            route["checkpoints"][i + 1]["lat"], route["checkpoints"][i + 1]["lon"]
        )

    checkpoint = route["checkpoints"][1]
    assert set(checkpoint) == {
        "index",
        "lat",
        "lon",
        "mile",
        "eta",
        "wind_mph",
        "gust_mph",
        "rain_in_hr",
        "snow_in_hr",
        "level",
        "driver",
    }
    assert checkpoint["mile"] == 25.0
    assert checkpoint["eta"].endswith("Z")
    assert (checkpoint["level"], checkpoint["driver"]) == ("low", "wind")


def test_unknown_checkpoint_is_serialised_with_nulls(client, plan_payload, use_planner):
    use_planner(
        [north_route("r1", 50, 1)], conditions=lambda c, h: HourValues(None, None, None, None, None)
    )
    route = post_plan(client, plan_payload).json()["routes"][0]
    assert all(segment["level"] == "unknown" for segment in route["segments"])
    checkpoint = route["checkpoints"][0]
    assert checkpoint["level"] == "unknown"
    assert checkpoint["driver"] is None
    assert checkpoint["wind_mph"] is None and checkpoint["rain_in_hr"] is None


def test_no_safe_route_and_stretch(client, plan_payload, use_planner):
    use_planner([north_route("r1", 50, 1)], conditions=lambda c, h: HourValues(70.0, 80.0, 0, 0, 0))
    body = post_plan(client, plan_payload).json()
    assert body["no_safe_route"] is True
    assert body["routes"][0]["summary"]["no_travel_stretches"] == [[0.0, 50.0]]
    assert body["routes"][0]["reason"].startswith("Least bad:")
    assert all(segment["level"] == "no_travel" for segment in body["routes"][0]["segments"])


def test_plan_passes_parsed_input_to_the_planner(client, plan_payload, use_planner):
    planner = use_planner([north_route("r1", 50, 1)])
    plan_payload["departure"] = iso_in(timedelta(hours=5))
    post_plan(client, plan_payload)
    origin, destination, kwargs = planner.routing.calls[0]
    assert origin == LatLon(32.7767, -96.797)
    assert destination == LatLon(39.7392, -104.9903)
    assert kwargs["load_lb"] == 42000
    assert kwargs["departure"].utcoffset() == timedelta(hours=-6)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderUnavailable("TomTom"), 502, "provider_unavailable"),
        (ProviderRateLimited("Open-Meteo", 60), 503, "provider_rate_limited"),
    ],
)
def test_provider_failures_use_the_error_envelope(
    client, plan_payload, use_planner, error, status, code
):
    class Failing:
        def routes(self, *args, **kwargs):
            raise error

    use_planner([], routing=Failing())
    response = post_plan(client, plan_payload)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_budget_error_is_422(client, plan_payload, use_planner):
    routes = [north_route(f"r{i}", 1500, 20, lon=-100 - i) for i in range(1, 4)]
    use_planner(routes)
    plan_payload["interval_mi"] = 10
    response = post_plan(client, plan_payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "budget_exceeded"


# --- geocode -------------------------------------------------------------------------------------


def test_geocode_returns_results(client, monkeypatch):
    class FakeGeocoder:
        def search(self, query, *, limit=5):
            assert query == "Dallas"
            return [Place("Dallas, TX", LatLon(32.7767, -96.797))]

    monkeypatch.setattr("trips.api.views.get_geocoder", lambda: FakeGeocoder())
    response = client.get("/api/geocode", {"q": "  Dallas "})
    assert response.status_code == 200
    assert response.json() == {"results": [{"label": "Dallas, TX", "lat": 32.7767, "lon": -96.797}]}


def test_missing_tomtom_key_is_a_readable_502(client, plan_payload, settings):
    settings.TOMTOM_API_KEY = ""
    response = post_plan(client, plan_payload)
    assert response.status_code == 502
    assert "not configured" in response.json()["error"]["message"]
