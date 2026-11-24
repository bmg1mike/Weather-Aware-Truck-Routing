"""Open-Meteo client, lattice cache and forecast-hour alignment (spec 5, 6.2)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.domain import LatLon
from trips.errors import ProviderRateLimited, ProviderUnavailable
from trips.services.weather import (
    HourValues,
    OpenMeteoWeatherProvider,
    WeatherLookup,
    checkpoint_weather,
    precip_hour,
    snap_to_lattice,
    wind_hour,
)

T0 = datetime(2026, 11, 25, 12, tzinfo=UTC)


def at(hours: float = 0, minutes: float = 0) -> datetime:
    return T0 + timedelta(hours=hours, minutes=minutes)


# --- lattice and hour alignment ------------------------------------------------------------------


def test_snap_to_lattice():
    assert snap_to_lattice(LatLon(32.7767, -96.7970)) == LatLon(32.8, -96.8)
    assert snap_to_lattice(LatLon(-0.04, 0.04)) == LatLon(0.0, 0.0)
    assert str(snap_to_lattice(LatLon(-0.04, 0.0)).lat) == "0.0"  # no "-0.0" cache keys


@pytest.mark.parametrize(
    ("eta", "expected"),
    [(at(0), at(0)), (at(minutes=29), at(0)), (at(minutes=30), at(1)), (at(minutes=59), at(1))],
)
def test_wind_uses_the_nearest_hour(eta, expected):
    assert wind_hour(eta) == expected


@pytest.mark.parametrize(
    ("eta", "expected"),
    [(at(0), at(0)), (at(minutes=1), at(1)), (at(minutes=59), at(1))],
)
def test_precipitation_uses_the_first_full_hour_at_or_after_eta(eta, expected):
    # Open-Meteo stamps precipitation sums at the END of the hour they cover.
    assert precip_hour(eta) == expected


def test_alignment_converts_offsets_to_utc():
    eta = datetime(2026, 11, 25, 6, 10, tzinfo=UTC).astimezone()  # any offset
    assert wind_hour(eta) == datetime(2026, 11, 25, 6, tzinfo=UTC)
    assert precip_hour(eta).tzinfo == UTC


# --- checkpoint weather --------------------------------------------------------------------------

CELL = LatLon(32.8, -96.8)


def values(**by_hour: HourValues) -> dict[tuple[LatLon, datetime], HourValues]:
    return {(CELL, at(int(h[1:]))): v for h, v in by_hour.items()}


def hv(wind=10.0, gust=20.0, rain=0.0, showers=0.0, snow=0.0) -> HourValues:
    return HourValues(wind, gust, rain, showers, snow)


def test_checkpoint_takes_wind_from_nearest_hour_and_precip_from_next_full_hour():
    lookup = values(
        h0=hv(wind=30, gust=41, rain=0.9), h1=hv(wind=99, gust=99, rain=0.2, showers=0.05, snow=0.6)
    )
    weather = checkpoint_weather(at(minutes=20), CELL, lookup)
    assert weather is not None
    assert (weather.wind_mph, weather.gust_mph) == (30, 41)
    assert weather.rain_in_hr == pytest.approx(0.25)  # rain + showers from the 13:00 stamp
    assert weather.snow_in_hr == 0.6


@pytest.mark.parametrize("missing", ["wind", "rain", "showers", "snow"])
def test_missing_scored_value_means_no_forecast(missing):
    lookup = values(h0=hv(**{missing: None}), h1=hv(**{missing: None}))
    assert checkpoint_weather(at(minutes=20), CELL, lookup) is None


def test_missing_hour_means_no_forecast():
    assert checkpoint_weather(at(minutes=20), CELL, values(h0=hv())) is None


def test_missing_gust_is_shown_as_unknown_but_not_fatal():
    weather = checkpoint_weather(at(0), CELL, values(h0=hv(gust=None)))
    assert weather is not None and weather.gust_mph is None


# --- Open-Meteo client ---------------------------------------------------------------------------


class FakeOpenMeteo:
    """Answers like Open-Meteo: wind = hour of day, gust = wind + 10, rain/showers/snow fixed."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        lats = params["latitude"].split(",")
        start = datetime.fromisoformat(params["start_hour"])
        end = datetime.fromisoformat(params["end_hour"])
        hours = [
            start + timedelta(hours=i)
            for i in range(int((end - start).total_seconds() // 3600) + 1)
        ]
        location = {
            "latitude": 0,
            "longitude": 0,
            "hourly": {
                "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
                "wind_speed_10m": [float(h.hour) for h in hours],
                "wind_gusts_10m": [h.hour + 10.0 for h in hours],
                "rain": [0.1] * len(hours),
                "showers": [0.05] * len(hours),
                "snowfall": [None] * len(hours),
            },
        }
        body = location if len(lats) == 1 else [location] * len(lats)
        return httpx.Response(200, json=body)


def provider_with(handler) -> OpenMeteoWeatherProvider:
    return OpenMeteoWeatherProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def cells(n: int) -> list[LatLon]:
    return [LatLon(30 + i / 10, -100.0) for i in range(n)]


def test_request_uses_five_variables_utc_units_and_only_the_needed_hours():
    fake = FakeOpenMeteo()
    provider_with(fake).hourly([CELL], start=at(0), end=at(3))
    params = fake.requests[0].url.params
    assert params["hourly"] == "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["timezone"] == "GMT"
    assert (params["start_hour"], params["end_hour"]) == ("2026-11-25T12:00", "2026-11-25T15:00")
    assert (params["latitude"], params["longitude"]) == ("32.8", "-96.8")


def test_parses_values_as_utc_hours_and_keeps_nulls():
    forecasts = provider_with(FakeOpenMeteo()).hourly([CELL], start=at(0), end=at(1))
    forecast = forecasts[CELL]
    assert forecast.times == (at(0), at(1))
    assert forecast.wind_mph == (12.0, 13.0)
    assert forecast.snow_in == (None, None)


def test_batches_at_most_100_coordinates_per_request():
    fake = FakeOpenMeteo()
    result = provider_with(fake).hourly(cells(250), start=at(0), end=at(0))
    sizes = sorted(len(r.url.params["latitude"].split(",")) for r in fake.requests)
    assert sizes == [50, 100, 100]
    assert len(result) == 250


def test_rate_limit_maps_to_provider_rate_limited():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "30"}, json={"reason": "limit"})

    with pytest.raises(ProviderRateLimited) as info:
        provider_with(handler).hourly([CELL], start=at(0), end=at(0))
    assert info.value.retry_after_s == 30


def test_timeout_is_retried_once():
    fake = FakeOpenMeteo()
    calls = []

    def flaky(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return fake(request)

    assert CELL in provider_with(flaky).hourly([CELL], start=at(0), end=at(0))
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("down", request=r)),
        lambda r: httpx.Response(503, text="maintenance"),
        lambda r: httpx.Response(400, json={"reason": "bad"}),
        lambda r: httpx.Response(200, text="not json"),
    ],
    ids=["timeout", "5xx", "4xx", "garbage"],
)
def test_persistent_failures_map_to_provider_unavailable(failure):
    with pytest.raises(ProviderUnavailable):
        provider_with(failure).hourly([CELL], start=at(0), end=at(0))


# --- lookup with per-cell, per-hour cache --------------------------------------------------------


@pytest.fixture
def cache(request):
    # LocMemCache instances with the same name share storage, so isolate each test.
    return LocMemCache(request.node.nodeid, {})


def test_lookup_fetches_only_the_window_needed(cache):
    fake = FakeOpenMeteo()
    lookup = WeatherLookup(provider_with(fake), cache)
    result = lookup.values({CELL: {at(1), at(3)}})
    params = fake.requests[0].url.params
    assert (params["start_hour"], params["end_hour"]) == ("2026-11-25T13:00", "2026-11-25T15:00")
    assert result[(CELL, at(3))].wind_mph == 15.0


def test_lookup_serves_repeat_requests_from_cache(cache):
    fake = FakeOpenMeteo()
    lookup = WeatherLookup(provider_with(fake), cache)
    first = lookup.values({CELL: {at(0), at(1)}})
    second = lookup.values({CELL: {at(0), at(1)}})
    assert first == second
    assert len(fake.requests) == 1


def test_lookup_requests_only_uncached_cells(cache):
    fake = FakeOpenMeteo()
    lookup = WeatherLookup(provider_with(fake), cache)
    lookup.values({CELL: {at(0)}})
    other = LatLon(35.2, -101.8)
    lookup.values({CELL: {at(0)}, other: {at(0)}})
    assert fake.requests[-1].url.params["latitude"] == "35.2"


def test_lookup_reports_cells_the_provider_did_not_return(cache):
    class Empty:
        def hourly(self, cells, *, start, end):
            return {}

    result = WeatherLookup(Empty(), cache).values({CELL: {at(0)}})
    assert result[(CELL, at(0))] == HourValues(None, None, None, None, None)
