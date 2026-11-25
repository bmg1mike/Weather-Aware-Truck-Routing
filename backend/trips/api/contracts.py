"""Wire contracts for the JSON API (spec section 8).

These TypedDicts are the single backend description of response shapes; they are mirrored by
``frontend/src/api/types.ts``. Change both together.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from trips.domain import CheckpointLevelSlug, Driver, SamplingInterval


class ErrorDetail(TypedDict):
    code: str
    message: str


class WeatherRequestJSON(TypedDict):
    """Forecasts the browser should fetch from Open-Meteo when the server is rate-limited."""

    cells: list[tuple[float, float]]
    """[lat, lon] lattice cells, in the order to request them."""
    start_hour: str
    """Open-Meteo ``start_hour`` / ``end_hour`` (UTC, ``YYYY-MM-DDTHH:MM``)."""
    end_hour: str


class ErrorResponse(TypedDict):
    error: ErrorDetail
    weather_request: NotRequired[WeatherRequestJSON]
    """Only on a 503 caused by Open-Meteo rate-limiting the server."""


class SuppliedForecastJSON(TypedDict):
    """One requested cell plus Open-Meteo's ``hourly`` block for it."""

    lat: float
    lon: float
    hourly: dict[str, list[float | str | None]]


# --- GET /api/geocode?q= -------------------------------------------------------------------------


class PlaceJSON(TypedDict):
    label: str
    lat: float
    lon: float


class GeocodeResponse(TypedDict):
    results: list[PlaceJSON]
    """Up to five suggestions."""


# --- POST /api/trips/plan ------------------------------------------------------------------------


class PlanRequest(TypedDict):
    origin: PlaceJSON
    destination: PlaceJSON
    departure: str
    """ISO 8601 with a UTC offset."""
    load_lb: int
    interval_mi: SamplingInterval
    forecasts: NotRequired[list[SuppliedForecastJSON]]
    """Browser-fetched forecasts, sent only when repeating a request after a weather_request."""


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
    """Known-forecast miles only. ``sum(miles_by_level) + unknown_mi == distance_mi``."""
    unknown_mi: float
    """Miles on segments touching a checkpoint with no forecast; never counted as Low."""
    avg_risk: float | None
    """Distance-weighted 0-4 over known miles; null when no segment has a forecast."""
    unknown_checkpoints: int
    no_travel_stretches: list[tuple[float, float]]
    """[start_mi, end_mi] ranges at No Travel, for the "no safe route" banner."""


class SegmentJSON(TypedDict):
    start_mi: float
    end_mi: float
    geometry: str
    """Encoded road geometry between consecutive checkpoints (precision 5)."""
    level: CheckpointLevelSlug
    """Computed by the backend scoring core, never re-derived by the frontend."""


class RouteJSON(TypedDict):
    id: str
    name: str
    """Display name in provider order, e.g. "Route A"; used by reason sentences."""
    rank: int
    reason: str
    distance_mi: float
    duration_s: int
    arrival: str
    geometry: str
    """Encoded polyline."""
    summary: RouteSummaryJSON
    checkpoints: list[CheckpointJSON]
    segments: list[SegmentJSON]


class CorridorJSON(TypedDict):
    bbox: tuple[float, float, float, float]
    """[min_lon, min_lat, max_lon, max_lat]."""
    max_grid_points: int
    """Locations left for the heatmap (<= 200); sent back as ``HeatmapRequest.max_points``."""


class PlanResponse(TypedDict):
    recommended_route_id: str
    no_safe_route: bool
    routes: list[RouteJSON]
    corridor: CorridorJSON


# --- POST /api/trips/heatmap ---------------------------------------------------------------------


class HeatmapRequest(TypedDict):
    bbox: tuple[float, float, float, float]
    route_geometries: list[str]
    start: str
    load_lb: int
    max_points: NotRequired[int]
    """Grid point cap from the plan's corridor (1-200, default 200)."""
    forecasts: NotRequired[list[SuppliedForecastJSON]]


class GridJSON(TypedDict):
    lats: list[float]
    lons: list[float]
    """Parallel arrays: grid point i is at (lats[i], lons[i]); row-major, south to north."""
    spacing_deg: float
    """Every point lies on multiples of this spacing, so the grid can be drawn as a raster."""


class HeatmapResponse(TypedDict):
    grid: GridJSON
    hours: int
    """Always 49: departure-relative hours 0 to 48."""
    risk: list[list[int | None]]
    """Per hour, per grid point: level 0-4, or null when the forecast is unavailable."""
    wind: list[list[float | None]]
    rain: list[list[float | None]]
    snow: list[list[float | None]]
