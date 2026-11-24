"""TomTom routing and geocoding clients, against a fake HTTP transport."""

from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.domain import LatLon
from trips.errors import NoRouteFound, ProviderRateLimited, ProviderUnavailable
from trips.services.geocoding import TomTomGeocodingProvider
from trips.services.routing import TomTomRoutingProvider

KEY = "secret-test-key"
ORIGIN, DEST = LatLon(32.7767, -96.797), LatLon(39.7392, -104.9903)
CST = timezone(timedelta(hours=-6))


@pytest.fixture
def cache(request):
    return LocMemCache(request.node.nodeid, {})


def departure(hours: float = 3) -> datetime:
    return (datetime.now(UTC) + timedelta(hours=hours)).astimezone(CST).replace(microsecond=0)


def tomtom_route(n_points=5, length_m=160_934, seconds=7200, progress=True, legs=1):
    """A due-north route: points 0.5 deg apart; progress anchors at the ends and the middle."""
    points = [{"latitude": 30 + 0.5 * i, "longitude": -100.0} for i in range(n_points)]
    per_leg = len(points) // legs
    leg_points = [points[i * per_leg : (i + 1) * per_leg + 1] for i in range(legs)]
    route = {
        "summary": {
            "lengthInMeters": length_m,
            "travelTimeInSeconds": seconds,
            "departureTime": "2026-11-25T06:00:00-06:00",
            "arrivalTime": "2026-11-25T07:00:00-07:00",
        },
        "legs": [{"points": pts} for pts in leg_points],
        "sections": [],
    }
    if progress:
        total = sum(len(p) for p in leg_points)
        route["progress"] = [
            {"pointIndex": 0, "travelTimeInSeconds": 0, "distanceInMeters": 0},
            {"pointIndex": 2, "travelTimeInSeconds": seconds // 4, "distanceInMeters": 1},
            {"pointIndex": total - 1, "travelTimeInSeconds": seconds, "distanceInMeters": length_m},
        ]
    return route


class Fake:
    def __init__(self, response=None, status=200, headers=None):
        self.requests: list[httpx.Request] = []
        self.response = response
        self.status = status
        self.headers = headers or {}

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, json=self.response, headers=self.headers)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


def routing(fake, cache):
    return TomTomRoutingProvider(fake.client(), KEY, cache)


# --- routing -------------------------------------------------------------------------------------


def test_request_asks_for_truck_routes_with_weight_departure_and_alternatives(cache):
    fake = Fake({"routes": [tomtom_route()]})
    depart = departure()
    routing(fake, cache).routes(ORIGIN, DEST, departure=depart, load_lb=42_000)
    request = fake.requests[0]
    assert request.url.path == "/routing/1/calculateRoute/32.7767,-96.797:39.7392,-104.9903/json"
    params = request.url.params
    assert params["travelMode"] == "truck"
    assert params["vehicleWeight"] == "19051"  # 42,000 lb in kg
    assert params["vehicleCommercial"] == "true"
    assert params["maxAlternatives"] == "2"
    assert datetime.fromisoformat(params["departAt"]) == depart
    assert params.get_list("extendedRouteRepresentation") == ["distance", "travelTime"]
    assert params["key"] == KEY


def test_departure_in_the_past_is_sent_as_now(cache):
    fake = Fake({"routes": [tomtom_route()]})
    routing(fake, cache).routes(ORIGIN, DEST, departure=departure(-0.05), load_lb=1)
    assert fake.requests[0].url.params["departAt"] == "now"


def test_via_points_go_between_origin_and_destination(cache):
    fake = Fake({"routes": [tomtom_route(legs=2)]})
    routing(fake, cache).routes(
        ORIGIN, DEST, departure=departure(), load_lb=1, via=[LatLon(37.6, -97.3)]
    )
    assert "32.7767,-96.797:37.6,-97.3:39.7392,-104.9903" in fake.requests[0].url.path


def test_parses_routes_into_domain_options(cache):
    fake = Fake({"routes": [tomtom_route(), tomtom_route(length_m=321_869, seconds=14400)]})
    depart = departure()
    routes = routing(fake, cache).routes(ORIGIN, DEST, departure=depart, load_lb=1)
    assert [r.id for r in routes] == ["r1", "r2"]
    first = routes[0]
    assert first.distance_mi == pytest.approx(100, abs=0.01)
    assert first.duration_s == 7200
    assert first.departure == depart
    assert first.arrival == depart + timedelta(hours=2)
    assert first.arrival.utcoffset() == timedelta(hours=-7)  # destination offset from TomTom
    assert first.points[0] == LatLon(30, -100) and len(first.points) == 5


def test_per_point_times_interpolate_progress_anchors(cache):
    fake = Fake({"routes": [tomtom_route(n_points=5, seconds=8000)]})
    route = routing(fake, cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)[0]
    offsets = route.point_offsets_s
    assert offsets is not None
    assert offsets[0] == 0 and offsets[2] == 2000 and offsets[4] == 8000
    assert offsets[1] == pytest.approx(1000, rel=0.01)  # evenly spaced points
    assert offsets[3] == pytest.approx(5000, rel=0.01)


def test_missing_progress_leaves_offsets_unset(cache):
    fake = Fake({"routes": [tomtom_route(progress=False)]})
    route = routing(fake, cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)[0]
    assert route.point_offsets_s is None


def test_multi_leg_junction_point_is_not_duplicated(cache):
    fake = Fake({"routes": [tomtom_route(n_points=5, legs=2)]})
    route = routing(fake, cache).routes(
        ORIGIN, DEST, departure=departure(), load_lb=1, via=[LatLon(31, -100)]
    )[0]
    assert len(route.points) == 5
    assert route.point_offsets_s is not None and len(route.point_offsets_s) == 5


def test_routes_are_cached_by_departure_hour_and_load(cache):
    fake = Fake({"routes": [tomtom_route()]})
    provider = routing(fake, cache)
    depart = departure().replace(minute=5)
    provider.routes(ORIGIN, DEST, departure=depart, load_lb=42_000)
    again = provider.routes(ORIGIN, DEST, departure=depart + timedelta(minutes=20), load_lb=42_000)
    assert len(fake.requests) == 1
    assert again[0].departure == depart + timedelta(minutes=20)  # ETAs follow the new departure
    provider.routes(ORIGIN, DEST, departure=depart, load_lb=42_001)
    assert len(fake.requests) == 2


def test_no_route_maps_to_no_route_error(cache):
    fake = Fake({"detailedError": {"code": "NO_ROUTE_FOUND", "message": "x"}}, status=400)
    with pytest.raises(NoRouteFound):
        routing(fake, cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)


def test_empty_route_list_maps_to_no_route_error(cache):
    with pytest.raises(NoRouteFound):
        routing(Fake({"routes": []}), cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)


def test_rejected_key_is_unavailable_and_does_not_leak_the_key(cache):
    fake = Fake({"detailedError": {"message": f"bad key {KEY}"}}, status=403)
    with pytest.raises(ProviderUnavailable) as info:
        routing(fake, cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)
    assert KEY not in info.value.message


def test_routing_rate_limit(cache):
    fake = Fake({}, status=429, headers={"Retry-After": "5"})
    with pytest.raises(ProviderRateLimited):
        routing(fake, cache).routes(ORIGIN, DEST, departure=departure(), load_lb=1)


def test_malformed_route_is_unavailable(cache):
    with pytest.raises(ProviderUnavailable):
        routing(Fake({"routes": [{"summary": {}}]}), cache).routes(
            ORIGIN, DEST, departure=departure(), load_lb=1
        )


# --- geocoding -----------------------------------------------------------------------------------


def geo_result(label, lat=32.7, lon=-96.8, country="US"):
    return {
        "type": "Geography",
        "address": {"freeformAddress": label, "countryCode": country},
        "position": {"lat": lat, "lon": lon},
    }


def geocoding(fake, cache):
    return TomTomGeocodingProvider(fake.client(), KEY, cache)


def test_geocode_restricts_to_us_and_encodes_the_query(cache):
    fake = Fake({"results": [geo_result("St. Louis, MO")]})
    places = geocoding(fake, cache).search("St. Louis, MO")
    request = fake.requests[0]
    assert request.url.raw_path.startswith(b"/search/2/geocode/St.%20Louis%2C%20MO.json")
    assert request.url.params["countrySet"] == "US"
    assert [(p.label, p.point) for p in places] == [("St. Louis, MO", LatLon(32.7, -96.8))]


def test_geocode_dedupes_labels_drops_non_us_and_limits_to_five(cache):
    results = [
        geo_result("Dallas, TX"),
        geo_result("dallas, tx", lat=33),
        geo_result("X", country="CA"),
    ]
    results += [geo_result(f"Place {i}") for i in range(10)]
    places = geocoding(Fake({"results": results}), cache).search("Dallas")
    assert [p.label for p in places] == ["Dallas, TX", "Place 0", "Place 1", "Place 2", "Place 3"]


def test_geocode_is_cached_per_normalised_query(cache):
    fake = Fake({"results": [geo_result("Denver, CO")]})
    provider = geocoding(fake, cache)
    provider.search("Denver")
    provider.search("  denver ")
    assert len(fake.requests) == 1


def test_geocode_failure_is_unavailable(cache):
    with pytest.raises(ProviderUnavailable):
        geocoding(Fake({}, status=403), cache).search("Denver")
