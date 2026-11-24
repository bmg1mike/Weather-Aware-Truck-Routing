"""Internal domain model shared by the services.

Pure: standard library only, no Django, no I/O. The pure-module guard test enforces this.
Distances are miles, speeds mph, precipitation inches per hour, weights lb (spec section 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Literal


class RiskLevel(IntEnum):
    """Ordered risk levels (spec 6.3). The integer value is the score used for averaging."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def slug(self) -> RiskSlug:
        return _SLUGS[self]


RiskSlug = Literal["low", "moderate", "high", "severe", "no_travel"]
CheckpointLevelSlug = RiskSlug | Literal["unknown"]
"""Wire value for a checkpoint level. ``unknown`` means no forecast: never treated as Low."""

_SLUGS: dict[RiskLevel, RiskSlug] = {
    RiskLevel.LOW: "low",
    RiskLevel.MODERATE: "moderate",
    RiskLevel.HIGH: "high",
    RiskLevel.SEVERE: "severe",
    RiskLevel.NO_TRAVEL: "no_travel",
}

Driver = Literal["wind", "rain", "snow"]
"""Which condition produced a checkpoint's level."""

SamplingInterval = Literal[10, 25, 50]
SAMPLING_INTERVALS_MI: tuple[SamplingInterval, ...] = (10, 25, 50)


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    point: LatLon


@dataclass(frozen=True, slots=True)
class RouteOption:
    """One route returned by a routing provider, before weather is attached."""

    id: str
    points: tuple[LatLon, ...]
    distance_mi: float
    duration_s: int
    departure: datetime
    arrival: datetime
    point_offsets_s: tuple[float, ...] | None = None
    """Seconds from departure at each point, when the provider supplies them (spec 6.1)."""


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    """Hourly forecast for one 0.1 degree lattice cell. Times are UTC hour stamps.

    Open-Meteo precipitation values are sums over the preceding hour. ``None`` marks a missing
    value, which must surface as an ``unknown`` checkpoint.
    """

    cell: LatLon
    times: tuple[datetime, ...]
    wind_mph: tuple[float | None, ...]
    gust_mph: tuple[float | None, ...]
    rain_in: tuple[float | None, ...]
    showers_in: tuple[float | None, ...]
    snow_in: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class CheckpointWeather:
    wind_mph: float
    gust_mph: float | None
    rain_in_hr: float
    snow_in_hr: float


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """A sampled point on a route. ``point`` is the true position; lookups use the lattice cell."""

    index: int
    point: LatLon
    mile: float
    eta: datetime
    weather: CheckpointWeather | None = None
    level: RiskLevel | None = None
    driver: Driver | None = None

    @property
    def level_slug(self) -> CheckpointLevelSlug:
        return "unknown" if self.level is None else self.level.slug
