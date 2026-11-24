"""Shared builders for request payloads."""

from datetime import UTC, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from django.utils import timezone

CST = dt_timezone(timedelta(hours=-6))


def iso_in(delta: timedelta) -> str:
    """An ISO 8601 timestamp ``delta`` from now, with a -06:00 offset."""
    return (timezone.now() + delta).astimezone(CST).isoformat()


def iso_utc_z(delta: timedelta) -> str:
    """Same instant style, but in UTC with the ``Z`` suffix browsers often send."""
    return (timezone.now() + delta).astimezone(UTC).isoformat().replace("+00:00", "Z")


def plan_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "origin": {"label": "Dallas, TX", "lat": 32.7767, "lon": -96.7970},
        "destination": {"label": "Denver, CO", "lat": 39.7392, "lon": -104.9903},
        "departure": iso_in(timedelta(hours=2)),
        "load_lb": 42000,
        "interval_mi": 25,
    }
    return payload | overrides


def heatmap_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "bbox": [-105.6, 32.2, -96.2, 40.3],
        "route_geometries": ["_p~iF~ps|U_ulLnnqC_mqNvxq`@"],
        "start": iso_in(timedelta(hours=2)),
        "load_lb": 42000,
    }
    return payload | overrides
