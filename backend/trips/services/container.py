"""Builds the real providers from settings. Views call these; tests replace them."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache

import httpx
from django.conf import settings
from django.core.cache import caches

from trips.domain import HourlyForecast, LatLon
from trips.errors import ProviderUnavailable
from trips.services.geocoding import GeocodingProvider, TomTomGeocodingProvider
from trips.services.heatmap import HeatmapBuilder
from trips.services.planner import TripPlanner
from trips.services.routing import TomTomRoutingProvider
from trips.services.weather import OpenMeteoWeatherProvider, SuppliedWeatherProvider, WeatherLookup


@cache
def _shared_client() -> httpx.Client:
    """One pooled client for all providers. Thread-safe, so weather batches can run in parallel."""
    return httpx.Client(
        timeout=httpx.Timeout(settings.PROVIDER_TIMEOUT_S),
        headers={"User-Agent": "weather-aware-truck-routing/0.1"},
    )


def http_client() -> httpx.Client:
    return _shared_client()


def _tomtom_key() -> str:
    key: str = settings.TOMTOM_API_KEY
    if not key:
        raise ProviderUnavailable("TomTom", "Routing is not configured on the server.")
    return key


def get_geocoder() -> GeocodingProvider:
    return TomTomGeocodingProvider(http_client(), _tomtom_key(), caches["default"])


def _weather() -> WeatherLookup:
    return WeatherLookup(OpenMeteoWeatherProvider(http_client()), caches["default"])


def supplied_weather(forecasts: Mapping[LatLon, HourlyForecast]) -> WeatherLookup:
    """Browser-fetched forecasts: the shared cache is read first but never written with them."""
    return WeatherLookup(SuppliedWeatherProvider(forecasts), caches["default"], cache_writes=False)


def get_heatmap_builder() -> HeatmapBuilder:
    return HeatmapBuilder(_weather(), wind_source=settings.WIND_SOURCE)


def get_planner() -> TripPlanner:
    return TripPlanner(
        TomTomRoutingProvider(http_client(), _tomtom_key(), caches["default"]),
        _weather(),
        wind_source=settings.WIND_SOURCE,
    )
