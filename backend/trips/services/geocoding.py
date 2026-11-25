"""Geocoding provider interface and TomTom Geocoding client (spec section 5).

Uses the TomTom Geocoding API, not the fuzzy Search API (2,500/month cap). Worldwide results;
places outside the US carry their country in the label. Duplicate labels are removed and results
are cached for 24 hours per normalised query.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from django.core.cache.backends.base import BaseCache

from trips.domain import LatLon, Place
from trips.errors import ProviderUnavailable
from trips.services.http import json_body, provider_get

logger = logging.getLogger(__name__)

PROVIDER = "TomTom"
GEOCODE_URL = "https://api.tomtom.com/search/2/geocode"
MAX_SUGGESTIONS = 5
CACHE_TTL_S = 24 * 60 * 60
# Ask for more than we show: duplicates and non-US results are dropped afterwards.
_FETCH_LIMIT = 10


class GeocodingProvider(Protocol):
    def search(self, query: str, *, limit: int = MAX_SUGGESTIONS) -> list[Place]:
        """Return up to ``limit`` places matching ``query``."""
        ...


def _collapse_spaces(query: str) -> str:
    return " ".join(query.split())


def _label(address: dict[str, Any]) -> str | None:
    """TomTom's free-form address, plus the country outside the US ("Paris" -> "Paris, France")."""
    label = address.get("freeformAddress")
    country = address.get("country")
    if not label or address.get("countryCode") == "US" or not country or country in label:
        return label if isinstance(label, str) else None
    return f"{label}, {country}"


class TomTomGeocodingProvider:
    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        cache: BaseCache,
        *,
        url: str = GEOCODE_URL,
        ttl_s: int = CACHE_TTL_S,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._cache = cache
        self._url = url
        self._ttl_s = ttl_s

    def search(self, query: str, *, limit: int = MAX_SUGGESTIONS) -> list[Place]:
        text = _collapse_spaces(query)
        key = f"geocode:v1:{quote(text.lower())}"  # search is case-insensitive; share the cache
        cached: list[tuple[str, float, float]] | None = self._cache.get(key)
        if cached is None:
            cached = self._fetch(text)
            self._cache.set(key, cached, timeout=self._ttl_s)
        return [Place(label, LatLon(lat, lon)) for label, lat, lon in cached[:limit]]

    def _fetch(self, query: str) -> list[tuple[str, float, float]]:
        params = {"key": self._api_key, "limit": _FETCH_LIMIT}
        url = f"{self._url}/{quote(query, safe='')}.json"
        response = provider_get(self._client, PROVIDER, url, params)
        if response.status_code != 200:
            logger.warning("TomTom geocoding returned %d", response.status_code)
            raise ProviderUnavailable(PROVIDER, "Place search is unavailable. Please try again.")
        body: Any = json_body(response, PROVIDER)
        places: list[tuple[str, float, float]] = []
        seen: set[str] = set()
        try:
            for result in body.get("results") or []:
                address = result["address"]
                label = _label(address)
                if not label or label.lower() in seen:
                    continue
                seen.add(label.lower())
                position = result["position"]
                places.append((label, float(position["lat"]), float(position["lon"])))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(
                PROVIDER, "TomTom sent an unexpected search response."
            ) from exc
        return places[:MAX_SUGGESTIONS]
