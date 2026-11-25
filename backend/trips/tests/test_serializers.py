"""Inputs the API must accept (spec section 4), checked independently of the endpoints."""

from datetime import timedelta

import pytest

from trips.api.serializers import (
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)
from trips.tests.helpers import heatmap_payload, iso_in, iso_utc_z, plan_payload


def valid_plan(**overrides):
    serializer = PlanRequestSerializer(data=plan_payload(**overrides))
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_allowed_intervals(interval):
    assert valid_plan(interval_mi=interval)["interval_mi"] == interval


def test_interval_defaults_to_25():
    payload = plan_payload()
    del payload["interval_mi"]
    serializer = PlanRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["interval_mi"] == 25


@pytest.mark.parametrize("load", [1, 30_000, 80_000, "42000"])
def test_load_bounds_are_inclusive(load):
    assert valid_plan(load_lb=load)["load_lb"] == int(load)


@pytest.mark.parametrize(
    "departure",
    [
        iso_in(-timedelta(minutes=4)),
        iso_in(timedelta(days=6, hours=23)),
        iso_utc_z(timedelta(hours=1)),
    ],
    ids=["inside-past-grace", "just-under-7-days", "z-suffix"],
)
def test_departure_window_and_formats(departure):
    parsed = valid_plan(departure=departure)["departure"]
    assert parsed.utcoffset() is not None


def test_places_outside_the_us_are_accepted():
    london = {"label": "London, United Kingdom", "lat": 51.5074, "lon": -0.1278}
    paris = {"label": "Paris, France", "lat": 48.8566, "lon": 2.3522}
    assert valid_plan(origin=london, destination=paris)["origin"]["lat"] == 51.5074


def test_heatmap_payload_is_accepted():
    serializer = HeatmapRequestSerializer(data=heatmap_payload())
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["bbox"] == (-105.6, 32.2, -96.2, 40.3)


def test_geocode_query_is_trimmed():
    serializer = GeocodeQuerySerializer(data={"q": "  Dallas  "})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["q"] == "Dallas"
