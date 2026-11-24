"""Corridor grid and the 49 hourly heatmap frames (spec section 7).

The grid is a regular lattice (multiples of ``spacing_deg``, itself a multiple of 0.1 degree, so
points share weather cache cells with checkpoints) clipped to ~30 miles around the routes. Spacing
starts at 0.3 degree and widens by 0.1 until at most 200 points remain. With checkpoints capped at
300 cells by the planner, a trip never needs more than 500 weather locations.

Frames are departure-relative: frame h is ``start + h hours`` for h = 0..48, classified with the
same hour alignment and ``classify`` as checkpoints.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from trips.domain import LatLon, RiskLevel
from trips.errors import BudgetExceeded
from trips.services.risk import classify
from trips.services.sampling import haversine_mi
from trips.services.weather import WeatherLookup, checkpoint_weather, hours_needed, snap_to_lattice

HOURS = 49  # slider hours 0 to 48 inclusive
CORRIDOR_BUFFER_MI = 30
MAX_GRID_POINTS = 200
START_SPACING_DEG = 0.3
SPACING_STEP_DEG = 0.1
MAX_SPACING_DEG = 1.0
_ROUTE_SAMPLE_MI = 2.0  # route densified to this spacing for corridor tests (<= 1 mi error)
_BUCKET_DEG = 0.5
_MI_PER_DEG_LAT = 69.0
WIND_DECIMALS = 1
PRECIP_DECIMALS = 3


@dataclass(frozen=True, slots=True)
class Grid:
    points: list[LatLon]
    """Row-major, south to north, then west to east."""
    spacing_deg: float


@dataclass(frozen=True, slots=True)
class Frames:
    times: list[datetime]
    risk: list[list[int | None]]
    wind: list[list[float | None]]
    rain: list[list[float | None]]
    snow: list[list[float | None]]


# --- corridor -----------------------------------------------------------------------------------


def _densify(route: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Route vertices thinned and filled in so consecutive samples are about ``step_mi`` apart."""
    if not route:
        return []
    samples = [route[0]]
    for a, b in pairwise(route):
        gap = haversine_mi(samples[-1], b)
        if gap < step_mi:
            continue
        pieces = math.ceil(haversine_mi(a, b) / step_mi)
        for i in range(1, pieces + 1):
            f = i / pieces
            samples.append(LatLon(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f))
    if samples[-1] != route[-1]:
        samples.append(route[-1])
    return samples


class _Corridor:
    """Answers "is this point within ``buffer_mi`` of any route?" using a coarse spatial hash."""

    def __init__(self, routes: Sequence[Sequence[LatLon]], buffer_mi: float) -> None:
        self.buffer_mi = buffer_mi
        self.buckets: dict[tuple[int, int], list[LatLon]] = defaultdict(list)
        for route in routes:
            for p in _densify(route, _ROUTE_SAMPLE_MI):
                self.buckets[self._bucket(p)].append(p)

    @staticmethod
    def _bucket(p: LatLon) -> tuple[int, int]:
        return math.floor(p.lat / _BUCKET_DEG), math.floor(p.lon / _BUCKET_DEG)

    def contains(self, p: LatLon) -> bool:
        lat_reach = self.buffer_mi / _MI_PER_DEG_LAT
        lon_reach = lat_reach / max(math.cos(math.radians(p.lat)), 0.05)
        row, col = self._bucket(p)
        rows = math.ceil(lat_reach / _BUCKET_DEG)
        cols = math.ceil(lon_reach / _BUCKET_DEG)
        for r in range(row - rows, row + rows + 1):
            for c in range(col - cols, col + cols + 1):
                for q in self.buckets.get((r, c), ()):
                    if haversine_mi(p, q) <= self.buffer_mi:
                        return True
        return False


def _lattice(bbox: tuple[float, float, float, float], spacing: float) -> list[LatLon]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lats = range(math.ceil(min_lat / spacing - 1e-9), math.floor(max_lat / spacing + 1e-9) + 1)
    lons = range(math.ceil(min_lon / spacing - 1e-9), math.floor(max_lon / spacing + 1e-9) + 1)
    return [
        LatLon(round(i * spacing, 1) + 0.0, round(j * spacing, 1) + 0.0) for i in lats for j in lons
    ]


def corridor_grid(
    bbox: tuple[float, float, float, float],
    routes: Sequence[Sequence[LatLon]],
    *,
    buffer_mi: float = CORRIDOR_BUFFER_MI,
    max_points: int = MAX_GRID_POINTS,
    start_spacing_deg: float = START_SPACING_DEG,
    max_spacing_deg: float = MAX_SPACING_DEG,
) -> Grid:
    corridor = _Corridor(routes, buffer_mi)
    spacing = start_spacing_deg
    while spacing <= max_spacing_deg + 1e-9:
        points = [p for p in _lattice(bbox, spacing) if corridor.contains(p)]
        if len(points) <= max_points:
            return Grid(points=sorted(points, key=lambda p: (p.lat, p.lon)), spacing_deg=spacing)
        spacing = round(spacing + SPACING_STEP_DEG, 1)
    raise BudgetExceeded(
        "This trip's corridor is too large for the free-tier weather budget, even at "
        f"{max_spacing_deg:.1f} degree spacing. Try a shorter trip."
    )


# --- frames -------------------------------------------------------------------------------------


class HeatmapBuilder:
    def __init__(self, weather: WeatherLookup, *, wind_source: str = "sustained") -> None:
        self.weather = weather
        self.wind_source = wind_source

    def build(self, points: Sequence[LatLon], start: datetime, *, load_lb: int) -> Frames:
        times = [start + timedelta(hours=h) for h in range(HOURS)]
        hours = set().union(*(hours_needed(t) for t in times))
        cells = [snap_to_lattice(p) for p in points]
        values = self.weather.values({cell: hours for cell in cells})

        frames = Frames(times=times, risk=[], wind=[], rain=[], snow=[])
        for t in times:
            risk: list[int | None] = []
            wind: list[float | None] = []
            rain: list[float | None] = []
            snow: list[float | None] = []
            for cell in cells:
                weather = checkpoint_weather(t, cell, values)
                scored = None
                if weather is not None:
                    scored = weather.gust_mph if self.wind_source == "gust" else weather.wind_mph
                if weather is None or scored is None:
                    risk.append(None)
                    wind.append(None)
                    rain.append(None)
                    snow.append(None)
                    continue
                level: RiskLevel = classify(
                    scored, weather.rain_in_hr, weather.snow_in_hr, load_lb
                ).level
                risk.append(int(level))
                wind.append(round(scored, WIND_DECIMALS))
                rain.append(round(weather.rain_in_hr, PRECIP_DECIMALS))
                snow.append(round(weather.snow_in_hr, PRECIP_DECIMALS))
            frames.risk.append(risk)
            frames.wind.append(wind)
            frames.rain.append(rain)
            frames.snow.append(snow)
        return frames
