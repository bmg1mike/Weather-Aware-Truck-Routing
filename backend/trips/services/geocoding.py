"""Geocoding provider interface and TomTom Geocoding client (spec section 5).

Uses the TomTom Geocoding API, not the fuzzy Search API (2,500/month cap). Results are cached for
24 hours. Implemented in plan phase 3.
"""

from __future__ import annotations

from typing import Protocol

from trips.domain import Place

MAX_SUGGESTIONS = 5


class GeocodingProvider(Protocol):
    def search(self, query: str, *, limit: int = MAX_SUGGESTIONS) -> list[Place]:
        """Return up to ``limit`` US places matching ``query``."""
        ...


class TomTomGeocodingProvider:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, *, limit: int = MAX_SUGGESTIONS) -> list[Place]:
        raise NotImplementedError("TomTom geocoding is implemented in plan phase 3.")
