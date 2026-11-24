"""Open-Meteo client, per-cell/per-hour cache and forecast alignment (spec sections 5 and 6.2).

Budget rules (Open-Meteo counts locations, not requests): coordinates are snapped to a 0.1 degree
lattice, at most 100 per request, five hourly variables, UTC, mph and inches, and only the hours
needed. Results are cached per lattice cell and forecast hour for 60 minutes.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from django.core.cache.backends.base import BaseCache

from trips.domain import CheckpointWeather, HourlyForecast, LatLon
from trips.errors import ProviderUnavailable
from trips.services.http import json_body, provider_get

logger = logging.getLogger(__name__)

PROVIDER = "Open-Meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_COORDS_PER_REQUEST = 100
HOURLY_VARIABLES = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")
LATTICE_DEG = 0.1
CACHE_TTL_S = 60 * 60
_HOUR_FORMAT = "%Y-%m-%dT%H:%M"
_MAX_PARALLEL_BATCHES = 4


class WeatherProvider(Protocol):
    def hourly(
        self, cells: Sequence[LatLon], *, start: datetime, end: datetime
    ) -> dict[LatLon, HourlyForecast]:
        """Hourly forecasts for lattice ``cells`` covering ``[start, end]`` (UTC hours).

        Cells the provider cannot serve are omitted; callers mark those checkpoints ``unknown``.
        """
        ...


# --- lattice and hour alignment ------------------------------------------------------------------


def snap_to_lattice(point: LatLon) -> LatLon:
    """Weather lookup cell for a point. The checkpoint keeps its true position for display."""

    def snap(value: float) -> float:
        return round(round(value / LATTICE_DEG) * LATTICE_DEG, 1) + 0.0  # + 0.0 drops "-0.0"

    return LatLon(snap(point.lat), snap(point.lon))


def _floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def wind_hour(eta: datetime) -> datetime:
    """Wind is an instantaneous value: use the hour nearest the ETA (half past rounds up)."""
    floor = _floor_hour(eta)
    return floor + timedelta(hours=1) if eta - floor >= timedelta(minutes=30) else floor


def precip_hour(eta: datetime) -> datetime:
    """Rain and snow are preceding-hour sums: use the first full hour at or after the ETA."""
    floor = _floor_hour(eta)
    return floor if eta == floor else floor + timedelta(hours=1)


def hours_needed(eta: datetime) -> set[datetime]:
    return {wind_hour(eta), precip_hour(eta)}


@dataclass(frozen=True, slots=True)
class HourValues:
    wind_mph: float | None
    gust_mph: float | None
    rain_in: float | None
    showers_in: float | None
    snow_in: float | None


MISSING = HourValues(None, None, None, None, None)


def checkpoint_weather(
    eta: datetime, cell: LatLon, values: Mapping[tuple[LatLon, datetime], HourValues]
) -> CheckpointWeather | None:
    """Weather at a checkpoint's ETA, or None when any scored value is missing (``unknown``)."""
    wind = values.get((cell, wind_hour(eta)), MISSING)
    precip = values.get((cell, precip_hour(eta)), MISSING)
    if (
        wind.wind_mph is None
        or precip.rain_in is None
        or precip.showers_in is None
        or precip.snow_in is None
    ):
        return None
    return CheckpointWeather(
        wind_mph=wind.wind_mph,
        gust_mph=wind.gust_mph,
        rain_in_hr=precip.rain_in + precip.showers_in,
        snow_in_hr=precip.snow_in,
    )


# --- Open-Meteo client --------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and math.isfinite(value) else None


def _parse_location(cell: LatLon, location: Any) -> HourlyForecast:
    try:
        hourly = location["hourly"]
        times = tuple(
            datetime.strptime(t, _HOUR_FORMAT).replace(tzinfo=UTC) for t in hourly["time"]
        )

        def series(name: str) -> tuple[float | None, ...]:
            raw = hourly.get(name) or []
            return tuple(_number(raw[i]) if i < len(raw) else None for i in range(len(times)))

        return HourlyForecast(
            cell=cell,
            times=times,
            wind_mph=series("wind_speed_10m"),
            gust_mph=series("wind_gusts_10m"),
            rain_in=series("rain"),
            showers_in=series("showers"),
            snow_in=series("snowfall"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderUnavailable(PROVIDER, "Open-Meteo sent an unexpected response.") from exc


class OpenMeteoWeatherProvider:
    def __init__(self, client: httpx.Client, url: str = FORECAST_URL) -> None:
        self._client = client
        self._url = url

    def hourly(
        self, cells: Sequence[LatLon], *, start: datetime, end: datetime
    ) -> dict[LatLon, HourlyForecast]:
        unique = list(dict.fromkeys(cells))
        batches = [
            unique[i : i + MAX_COORDS_PER_REQUEST]
            for i in range(0, len(unique), MAX_COORDS_PER_REQUEST)
        ]
        if not batches:
            return {}
        with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_BATCHES, len(batches))) as pool:
            results = list(pool.map(lambda batch: self._fetch(batch, start, end), batches))
        return {cell: forecast for batch in results for cell, forecast in batch.items()}

    def _fetch(
        self, batch: Sequence[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlyForecast]:
        params = {
            "latitude": ",".join(str(c.lat) for c in batch),
            "longitude": ",".join(str(c.lon) for c in batch),
            "hourly": ",".join(HOURLY_VARIABLES),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "start_hour": start.astimezone(UTC).strftime(_HOUR_FORMAT),
            "end_hour": end.astimezone(UTC).strftime(_HOUR_FORMAT),
        }
        response = provider_get(self._client, PROVIDER, self._url, params)
        if response.status_code != 200:
            logger.warning("Open-Meteo returned %d: %s", response.status_code, response.text[:200])
            raise ProviderUnavailable(PROVIDER, "Open-Meteo rejected the forecast request.")
        body = json_body(response, PROVIDER)
        locations = body if isinstance(body, list) else [body]
        if len(locations) != len(batch):
            raise ProviderUnavailable(PROVIDER, "Open-Meteo sent an unexpected response.")
        return {
            cell: _parse_location(cell, loc) for cell, loc in zip(batch, locations, strict=True)
        }


# --- cached lookup -------------------------------------------------------------------------------


def _cache_key(cell: LatLon, hour: datetime) -> str:
    return f"wx:v1:{cell.lat:.1f}:{cell.lon:.1f}:{hour:%Y%m%dT%H}"


class WeatherLookup:
    """Hour values for (cell, hour) pairs, served from cache where possible.

    Uncached cells are fetched in one window spanning only the hours they need. Gaps the provider
    leaves are returned as ``MISSING`` and not cached, so they are retried on the next plan.
    """

    def __init__(self, provider: WeatherProvider, cache: BaseCache, ttl_s: int = CACHE_TTL_S):
        self._provider = provider
        self._cache = cache
        self._ttl_s = ttl_s

    def values(
        self, needs: Mapping[LatLon, set[datetime]]
    ) -> dict[tuple[LatLon, datetime], HourValues]:
        wanted = {
            (cell, hour): _cache_key(cell, hour) for cell, hours in needs.items() for hour in hours
        }
        cached = self._cache.get_many(list(wanted.values()))
        result: dict[tuple[LatLon, datetime], HourValues] = {}
        missing: dict[LatLon, set[datetime]] = {}
        for pair, key in wanted.items():
            if key in cached:
                result[pair] = HourValues(*cached[key])
            else:
                missing.setdefault(pair[0], set()).add(pair[1])

        if missing:
            all_hours = [hour for hours in missing.values() for hour in hours]
            forecasts = self._provider.hourly(
                list(missing), start=min(all_hours), end=max(all_hours)
            )
            to_cache: dict[str, tuple[float | None, ...]] = {}
            for cell, forecast in forecasts.items():
                for i, hour in enumerate(forecast.times):
                    hv = HourValues(
                        forecast.wind_mph[i],
                        forecast.gust_mph[i],
                        forecast.rain_in[i],
                        forecast.showers_in[i],
                        forecast.snow_in[i],
                    )
                    if hv != MISSING:
                        to_cache[_cache_key(cell, hour)] = (
                            hv.wind_mph,
                            hv.gust_mph,
                            hv.rain_in,
                            hv.showers_in,
                            hv.snow_in,
                        )
                    if hour in missing.get(cell, ()):
                        result[(cell, hour)] = hv
            self._cache.set_many(to_cache, timeout=self._ttl_s)
            for cell, hours in missing.items():
                for hour in hours:
                    result.setdefault((cell, hour), MISSING)
        return result
