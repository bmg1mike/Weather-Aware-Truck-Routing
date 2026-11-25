"""Browser weather fallback: when Open-Meteo rate-limits the server's (shared) IP address, the API
says which forecasts it needs, the browser fetches them from its own address, and the same request
is repeated with them. Risk is still classified here, and supplied data is never cached."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.errors import ProviderRateLimited
from trips.services.heatmap import HeatmapBuilder
from trips.services.planner import TripPlanner
from trips.services.weather import WeatherLookup
from trips.tests.test_endpoints import heatmap_request
from trips.tests.test_planner import FakeRouting, north_route

HOUR = "%Y-%m-%dT%H:%M"


class RateLimitedWeather:
    def __init__(self, retry_after_s=37_632):
        self.retry_after_s = retry_after_s
        self.calls = 0

    def hourly(self, cells, *, start, end):
        self.calls += 1
        raise ProviderRateLimited("Open-Meteo", self.retry_after_s)


@pytest.fixture
def rate_limited(monkeypatch, request):
    """Plans and heatmaps whose server-side Open-Meteo calls are all rate-limited."""
    weather = RateLimitedWeather()
    lookup = WeatherLookup(weather, LocMemCache(request.node.nodeid, {}))
    routing = FakeRouting([north_route("r1", 100, 2)])
    monkeypatch.setattr("trips.api.views.get_planner", lambda: TripPlanner(routing, lookup))
    monkeypatch.setattr("trips.api.views.get_heatmap_builder", lambda: HeatmapBuilder(lookup))
    return weather


def open_meteo_locations(weather_request, wind_mph=60.0):
    """What the browser sends back: each requested cell with Open-Meteo's ``hourly`` block."""
    start = datetime.strptime(weather_request["start_hour"], HOUR).replace(tzinfo=UTC)
    end = datetime.strptime(weather_request["end_hour"], HOUR).replace(tzinfo=UTC)
    times = []
    while start <= end:
        times.append(start.strftime(HOUR))
        start += timedelta(hours=1)
    n = len(times)
    return [
        {
            "lat": lat,
            "lon": lon,
            "hourly": {
                "time": times,
                "wind_speed_10m": [wind_mph] * n,
                "wind_gusts_10m": [wind_mph + 10] * n,
                "rain": [0.0] * n,
                "showers": [0.0] * n,
                "snowfall": [0.0] * n,
            },
        }
        for lat, lon in weather_request["cells"]
    ]


def post(client, path, payload):
    response = client.post(path, payload, format="json")
    return response.status_code, response.json()


def test_rate_limited_plan_names_the_forecasts_the_browser_should_fetch(
    client, plan_payload, rate_limited
):
    status, body = post(client, "/api/trips/plan", plan_payload)
    assert status == 503
    assert body["error"]["code"] == "provider_rate_limited"
    assert "about 10 hours" in body["error"]["message"]
    request = body["weather_request"]
    assert request["cells"] and all(len(cell) == 2 for cell in request["cells"])
    assert request["start_hour"] <= request["end_hour"]


def test_plan_retried_with_browser_forecasts_is_classified_on_the_server(
    client, plan_payload, rate_limited
):
    _, body = post(client, "/api/trips/plan", plan_payload)
    forecasts = open_meteo_locations(body["weather_request"], wind_mph=60.0)
    calls_before = rate_limited.calls

    status, body = post(client, "/api/trips/plan", {**plan_payload, "forecasts": forecasts})

    assert status == 200
    levels = {cp["level"] for cp in body["routes"][0]["checkpoints"]}
    assert levels == {"no_travel"}  # 60 mph wind, escalated by the 42,000 lb load in risk.py
    assert rate_limited.calls == calls_before  # the server did not call Open-Meteo again


def test_browser_forecasts_are_not_cached_for_other_requests(client, plan_payload, rate_limited):
    _, body = post(client, "/api/trips/plan", plan_payload)
    forecasts = open_meteo_locations(body["weather_request"])
    assert post(client, "/api/trips/plan", {**plan_payload, "forecasts": forecasts})[0] == 200

    status, _ = post(client, "/api/trips/plan", plan_payload)
    assert status == 503


def test_rate_limited_heatmap_can_be_retried_with_browser_forecasts(client, rate_limited):
    heatmap_payload = heatmap_request()
    status, body = post(client, "/api/trips/heatmap", heatmap_payload)
    assert status == 503 and body["weather_request"]["cells"]

    forecasts = open_meteo_locations(body["weather_request"], wind_mph=10.0)
    status, body = post(client, "/api/trips/heatmap", {**heatmap_payload, "forecasts": forecasts})

    assert status == 200
    assert len(body["risk"]) == 49
    assert {level for frame in body["risk"] for level in frame} == {0}


@pytest.mark.parametrize(
    "bad",
    [
        [{"lat": 35.0, "lon": -100.0, "hourly": {"time": ["not-a-time"]}}],
        [{"lat": 95.0, "lon": -100.0, "hourly": {"time": []}}],
        "not-a-list",
    ],
    ids=["bad-time", "bad-latitude", "not-a-list"],
)
def test_malformed_browser_forecasts_are_a_validation_error(
    client, plan_payload, rate_limited, bad
):
    status, body = post(client, "/api/trips/plan", {**plan_payload, "forecasts": bad})
    assert status == 400 and body["error"]["code"] == "validation_error"
    assert body["error"]["message"].startswith("forecasts")
