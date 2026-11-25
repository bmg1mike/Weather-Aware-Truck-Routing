"""Domain results → JSON contracts (``trips/api/contracts.py``)."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from itertools import pairwise

from trips.api.contracts import (
    CheckpointJSON,
    GeocodeResponse,
    HeatmapResponse,
    MilesByLevel,
    PlanResponse,
    RouteJSON,
    SegmentJSON,
)
from trips.domain import Checkpoint, Place, RiskLevel
from trips.services.heatmap import HOURS, Frames, Grid
from trips.services.planner import PlannedRoute, TripPlan
from trips.services.sampling import cumulative_miles, encode_polyline
from trips.services.scoring import segments

COORD_DECIMALS = 5
MILE_DECIMALS = 1
WIND_DECIMALS = 1
PRECIP_DECIMALS = 3


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def _iso_utc(moment: datetime) -> str:
    return _iso(moment.astimezone(UTC)).replace("+00:00", "Z")


def _round(value: float | None, decimals: int) -> float | None:
    return None if value is None else round(value, decimals)


def checkpoint_json(cp: Checkpoint) -> CheckpointJSON:
    weather = cp.weather
    wind = gust = rain = snow = None
    if weather is not None:
        wind, gust = weather.wind_mph, weather.gust_mph
        rain, snow = weather.rain_in_hr, weather.snow_in_hr
    return {
        "index": cp.index,
        "lat": round(cp.point.lat, COORD_DECIMALS),
        "lon": round(cp.point.lon, COORD_DECIMALS),
        "mile": round(cp.mile, MILE_DECIMALS),
        "eta": _iso_utc(cp.eta),
        "wind_mph": _round(wind, WIND_DECIMALS),
        "gust_mph": _round(gust, WIND_DECIMALS),
        "rain_in_hr": _round(rain, PRECIP_DECIMALS),
        "snow_in_hr": _round(snow, PRECIP_DECIMALS),
        "level": cp.level_slug,
        "driver": cp.driver if cp.level is not None else None,
    }


def _segments_json(route: PlannedRoute) -> list[SegmentJSON]:
    option = route.option
    distances = cumulative_miles(option.points, total_mi=option.distance_mi)
    result: list[SegmentJSON] = []
    for (start, end), segment in zip(
        pairwise(route.checkpoints), segments(route.checkpoints), strict=True
    ):
        first = bisect_right(distances, segment.start_mi)
        last = bisect_left(distances, segment.end_mi)
        points = (start.point, *option.points[first:last], end.point)
        result.append(
            {
                "start_mi": round(segment.start_mi, MILE_DECIMALS),
                "end_mi": round(segment.end_mi, MILE_DECIMALS),
                "geometry": encode_polyline(points),
                "level": "unknown" if segment.level is None else segment.level.slug,
            }
        )
    return result


def route_json(route: PlannedRoute) -> RouteJSON:
    miles = route.summary.miles_by_level
    miles_json: MilesByLevel = {
        "low": round(miles[RiskLevel.LOW], MILE_DECIMALS),
        "moderate": round(miles[RiskLevel.MODERATE], MILE_DECIMALS),
        "high": round(miles[RiskLevel.HIGH], MILE_DECIMALS),
        "severe": round(miles[RiskLevel.SEVERE], MILE_DECIMALS),
        "no_travel": round(miles[RiskLevel.NO_TRAVEL], MILE_DECIMALS),
    }
    option = route.option
    return {
        "id": option.id,
        "name": route.name,
        "rank": route.rank,
        "reason": route.reason,
        "distance_mi": round(option.distance_mi, MILE_DECIMALS),
        "duration_s": option.duration_s,
        "arrival": _iso(option.arrival),
        "geometry": encode_polyline(option.points),
        "summary": {
            "miles_by_level": miles_json,
            "unknown_mi": round(route.summary.unknown_mi, MILE_DECIMALS),
            "avg_risk": route.summary.avg_risk,
            "unknown_checkpoints": route.summary.unknown_checkpoints,
            "no_travel_stretches": [
                (round(start, MILE_DECIMALS), round(end, MILE_DECIMALS))
                for start, end in route.no_travel_stretches
            ],
        },
        "checkpoints": [checkpoint_json(cp) for cp in route.checkpoints],
        "segments": _segments_json(route),
    }


def plan_json(plan: TripPlan) -> PlanResponse:
    return {
        "recommended_route_id": plan.recommended_id,
        "no_safe_route": plan.no_safe_route,
        "routes": [route_json(route) for route in plan.routes],
        "corridor": {
            "bbox": tuple(round(v, 4) for v in plan.bbox),  # type: ignore[typeddict-item]
            "max_grid_points": plan.max_grid_points,
        },
    }


def geocode_json(places: list[Place]) -> GeocodeResponse:
    return {"results": [{"label": p.label, "lat": p.point.lat, "lon": p.point.lon} for p in places]}


def heatmap_json(grid: Grid, frames: Frames) -> HeatmapResponse:
    return {
        "grid": {
            "lats": [p.lat for p in grid.points],
            "lons": [p.lon for p in grid.points],
            "spacing_deg": grid.spacing_deg,
        },
        "hours": HOURS,
        "risk": frames.risk,
        "wind": frames.wind,
        "rain": frames.rain,
        "snow": frames.snow,
    }
