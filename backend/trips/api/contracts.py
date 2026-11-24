"""Wire contracts for the JSON API (spec section 8).

These TypedDicts are the single backend description of response shapes; they are mirrored by
``frontend/src/api/types.ts``. Change both together.
"""

from __future__ import annotations

from typing import TypedDict

from trips.domain import CheckpointLevelSlug, Driver, SamplingInterval


class ErrorDetail(TypedDict):
    code: str
    message: str


class ErrorResponse(TypedDict):
    error: ErrorDetail


# --- GET /api/geocode?q= ------------------------------------------------------------------------


class PlaceJSON(TypedDict):
    label: str
    lat: float
    lon: float


class GeocodeResponse(TypedDict):
    results: list[PlaceJSON]
    """Up to five suggestions."""


# --- POST /api/trips/plan -----------------------------------------------------------------------


class PlanRequest(TypedDict):
    origin: PlaceJSON
    destination: PlaceJSON
    departure: str
    """ISO 8601 with a UTC offset."""
    load_lb: int
    interval_mi: SamplingInterval


class CheckpointJSON(TypedDict):
    index: int
    lat: float
    lon: float
    mile: float
    eta: str
    wind_mph: float | None
    gust_mph: float | None
    rain_in_hr: float | None
    snow_in_hr: float | None
    level: CheckpointLevelSlug
    driver: Driver | None


class MilesByLevel(TypedDict):
    low: float
    moderate: float
    high: float
    severe: float
    no_travel: float


class RouteSummaryJSON(TypedDict):
    miles_by_level: MilesByLevel
    avg_risk: float
    unknown_checkpoints: int


class RouteJSON(TypedDict):
    id: str
    rank: int
    reason: str
    distance_mi: float
    duration_s: int
    arrival: str
    geometry: str
    """Encoded polyline."""
    summary: RouteSummaryJSON
    checkpoints: list[CheckpointJSON]


class CorridorJSON(TypedDict):
    bbox: tuple[float, float, float, float]
    """[min_lon, min_lat, max_lon, max_lat]."""


class PlanResponse(TypedDict):
    recommended_route_id: str
    no_safe_route: bool
    routes: list[RouteJSON]
    corridor: CorridorJSON


# --- POST /api/trips/heatmap --------------------------------------------------------------------


class HeatmapRequest(TypedDict):
    bbox: tuple[float, float, float, float]
    route_geometries: list[str]
    start: str
    load_lb: int


class GridJSON(TypedDict):
    lats: list[float]
    lons: list[float]


class HeatmapResponse(TypedDict):
    grid: GridJSON
    hours: int
    """Always 49: departure-relative hours 0 to 48."""
    risk: list[list[int | None]]
    """Per hour, per grid point: level 0-4, or null when the forecast is unavailable."""
    wind: list[list[float | None]]
    rain: list[list[float | None]]
    snow: list[list[float | None]]
