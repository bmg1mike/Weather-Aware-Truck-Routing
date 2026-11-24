"""Weather provider interface and Open-Meteo client (spec sections 5 and 6.2).

Budget rules (Open-Meteo counts locations, not requests): at most 100 coordinates per request,
five hourly variables, only the hours needed, UTC, mph and inches. Lookups are keyed by 0.1 degree
lattice cell and cached per cell and forecast hour for 60 minutes. Implemented in plan phase 3.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from trips.domain import HourlyForecast, LatLon

MAX_COORDS_PER_REQUEST = 100
HOURLY_VARIABLES = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")


class WeatherProvider(Protocol):
    def hourly(
        self, cells: Sequence[LatLon], *, start: datetime, end: datetime
    ) -> dict[LatLon, HourlyForecast]:
        """Hourly forecasts for lattice ``cells`` covering ``[start, end]`` (UTC hours).

        Cells the provider cannot serve are omitted; callers mark those checkpoints ``unknown``.
        """
        ...


class OpenMeteoWeatherProvider:
    def hourly(
        self, cells: Sequence[LatLon], *, start: datetime, end: datetime
    ) -> dict[LatLon, HourlyForecast]:
        raise NotImplementedError("Open-Meteo lookups are implemented in plan phase 3.")
