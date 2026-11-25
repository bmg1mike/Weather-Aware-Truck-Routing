"""Endpoint wiring and request rejection over HTTP (spec sections 4 and 8)."""

from datetime import timedelta

import pytest

from trips.tests.helpers import iso_in


def error_of(response):
    return response.json()["error"]


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- plan ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval_mi", 20),
        ("load_lb", 0),
        ("load_lb", 80_001),
        ("load_lb", 42000.5),
        ("load_lb", True),
        ("load_lb", "heavy"),
        ("departure", "2026-11-25T06:00:00"),  # no offset
        ("departure", "tomorrow morning"),
        ("departure", iso_in(-timedelta(minutes=6))),  # beyond 5 minute grace
        ("departure", iso_in(timedelta(days=7, minutes=1))),
    ],
)
def test_invalid_plan_fields(client, plan_payload, field, value):
    plan_payload[field] = value
    response = client.post("/api/trips/plan", plan_payload, format="json")
    assert response.status_code == 400
    assert error_of(response)["code"] == "validation_error"
    assert error_of(response)["message"].startswith(f"{field}:")


@pytest.mark.parametrize(
    ("key", "value"),
    [("lat", 91), ("lon", -181), ("lat", "nan"), ("lon", "inf"), ("label", "")],
)
def test_invalid_place(client, plan_payload, key, value):
    plan_payload["origin"][key] = value
    response = client.post("/api/trips/plan", plan_payload, format="json")
    assert response.status_code == 400
    assert error_of(response)["message"].startswith(f"origin.{key}:")


def test_origin_must_differ_from_destination(client, plan_payload):
    plan_payload["destination"] = dict(plan_payload["origin"], label="Same place")
    response = client.post("/api/trips/plan", plan_payload, format="json")
    assert response.status_code == 400
    assert "differ" in error_of(response)["message"]


@pytest.mark.parametrize("missing", ["origin", "destination", "departure", "load_lb"])
def test_required_plan_fields(client, plan_payload, missing):
    del plan_payload[missing]
    response = client.post("/api/trips/plan", plan_payload, format="json")
    assert response.status_code == 400
    assert error_of(response)["message"].startswith(f"{missing}:")


# --- heatmap -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bbox", [-96.2, 32.2, -105.6, 40.3]),  # min_lon > max_lon
        ("bbox", [-105.6, 32.2, -96.2]),
        ("bbox", [-105.6, "nan", -96.2, 40.3]),
        ("route_geometries", []),
        ("route_geometries", ["a", "b", "c", "d"]),
        ("start", "2026-11-25T06:00:00"),
        ("load_lb", 0),
        ("route_geometries", ["not a polyline!"]),
        ("route_geometries", ["_p~iF~ps|U"]),  # a single point is not a route
        ("max_points", 0),
        ("max_points", 201),
    ],
)
def test_invalid_heatmap_fields(client, heatmap_payload, field, value):
    heatmap_payload[field] = value
    response = client.post("/api/trips/heatmap", heatmap_payload, format="json")
    assert response.status_code == 400
    assert error_of(response)["message"].startswith(f"{field}")


# --- geocode -------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", [None, "", "Da", "  D  "])
def test_geocode_requires_three_characters(client, query):
    params = {} if query is None else {"q": query}
    response = client.get("/api/geocode", params)
    assert response.status_code == 400
    assert error_of(response)["code"] == "validation_error"
