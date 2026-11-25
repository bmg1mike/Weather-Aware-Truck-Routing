"""Request validation (spec section 4). Validation failures render as ``validation_error``."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from trips.domain import SAMPLING_INTERVALS_MI, LatLon
from trips.services.sampling import decode_polyline

MIN_LOAD_LB = 1
MAX_LOAD_LB = 80_000
DEPARTURE_PAST_GRACE = timedelta(minutes=5)
# [ASSUMPTION] spec section 4: keep every checkpoint ETA inside the forecast window.
DEPARTURE_MAX_AHEAD = timedelta(days=7)
# The heatmap is requested after the plan, so its start may have slipped slightly into the past.
HEATMAP_START_PAST_GRACE = timedelta(hours=1)
SAME_PLACE_TOLERANCE_DEG = 1e-4  # about 11 m
MIN_GEOCODE_QUERY = 3
MAX_ROUTES = 3


def parse_offset_datetime(value: str, *, past_grace: timedelta) -> datetime:
    """Parse ISO 8601 that carries an explicit UTC offset and lies inside the forecast window."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise serializers.ValidationError("Must be an ISO 8601 date-time.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise serializers.ValidationError("Must include a UTC offset, e.g. 2026-11-25T06:00-06:00.")
    now = timezone.now()
    if parsed < now - past_grace:
        raise serializers.ValidationError("Departure cannot be in the past.")
    if parsed > now + DEPARTURE_MAX_AHEAD:
        raise serializers.ValidationError("Departure must be within the next 7 days.")
    return parsed


class FiniteFloatField(serializers.FloatField):
    """FloatField that rejects NaN and infinity (``float("nan")`` slips past range checks)."""

    def to_internal_value(self, data: Any) -> float:
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("Must be a finite number.")
        return value


class PlaceSerializer(serializers.Serializer[dict[str, Any]]):
    # The wire name "label" shadows DRF's Field.label attribute in the type stubs only.
    label = serializers.CharField(max_length=200, trim_whitespace=True)  # type: ignore[assignment]
    lat = FiniteFloatField(min_value=-90, max_value=90)
    lon = FiniteFloatField(min_value=-180, max_value=180)


class LoadField(serializers.IntegerField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(min_value=MIN_LOAD_LB, max_value=MAX_LOAD_LB, **kwargs)

    def to_internal_value(self, data: Any) -> int:
        # Reject booleans and fractional values: load is a whole number of pounds.
        if isinstance(data, bool) or (isinstance(data, float) and not data.is_integer()):
            raise serializers.ValidationError("Must be a whole number of pounds.")
        return int(super().to_internal_value(data))


class PlanRequestSerializer(serializers.Serializer[dict[str, Any]]):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.CharField()
    load_lb = LoadField()
    interval_mi = serializers.ChoiceField(choices=SAMPLING_INTERVALS_MI, default=25)

    def validate_departure(self, value: str) -> datetime:
        return parse_offset_datetime(value, past_grace=DEPARTURE_PAST_GRACE)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        origin, destination = attrs["origin"], attrs["destination"]
        if (
            abs(origin["lat"] - destination["lat"]) < SAME_PLACE_TOLERANCE_DEG
            and abs(origin["lon"] - destination["lon"]) < SAME_PLACE_TOLERANCE_DEG
        ):
            raise serializers.ValidationError("Origin and destination must differ.")
        return attrs


class HeatmapRequestSerializer(serializers.Serializer[dict[str, Any]]):
    bbox = serializers.ListField(child=FiniteFloatField(), min_length=4, max_length=4)
    route_geometries = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False), min_length=1, max_length=MAX_ROUTES
    )
    start = serializers.CharField()
    load_lb = LoadField()
    max_points = serializers.IntegerField(min_value=1, max_value=200, default=200)

    def validate_start(self, value: str) -> datetime:
        return parse_offset_datetime(value, past_grace=HEATMAP_START_PAST_GRACE)

    def validate_route_geometries(self, value: list[str]) -> list[list[LatLon]]:
        routes = []
        for encoded in value:
            try:
                points = decode_polyline(encoded)
            except ValueError as exc:
                raise serializers.ValidationError(
                    "Each route must be an encoded polyline."
                ) from exc
            if len(points) < 2 or not all(
                -90 <= p.lat <= 90 and -180 <= p.lon <= 180 for p in points
            ):
                raise serializers.ValidationError("Each route must be an encoded polyline.")
            routes.append(points)
        return routes

    def validate_bbox(self, value: list[float]) -> tuple[float, float, float, float]:
        min_lon, min_lat, max_lon, max_lat = value
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise serializers.ValidationError("Must be [min_lon, min_lat, max_lon, max_lat].")
        return (min_lon, min_lat, max_lon, max_lat)


class GeocodeQuerySerializer(serializers.Serializer[dict[str, Any]]):
    q = serializers.CharField(min_length=MIN_GEOCODE_QUERY, max_length=200, trim_whitespace=True)
