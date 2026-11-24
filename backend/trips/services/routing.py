"""Routing provider interface and TomTom client (spec section 5).

TomTom Routing API v1 ``calculateRoute`` with ``travelMode=truck``, ``vehicleWeight``, ``departAt``
and ``maxAlternatives=2``: one request returns up to three routes. The client is implemented in
plan phase 3 after the phase 0 truck-mode smoke test.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from trips.domain import LatLon, RouteOption


class RoutingProvider(Protocol):
    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        departure: datetime,
        load_lb: int,
        max_alternatives: int = 2,
        via: Sequence[LatLon] = (),
        relaxed: bool = False,
    ) -> list[RouteOption]:
        """Return up to ``max_alternatives + 1`` routes, primary first.

        ``via`` forces the route through intermediate points and ``relaxed`` lowers the minimum
        deviation between alternatives; both serve the fewer-than-three-routes fallback (spec 5).
        Raises ``ProviderUnavailable`` on timeout/bad response and ``ProviderRateLimited`` on 429.
        """
        ...


class TomTomRoutingProvider:
    """Phase 3. Holds the server-side key; never expose it to the client.

    If the phase 0 smoke test shows truck mode is unavailable on the free tier, the documented
    fallback (``travelMode=car``, 65 mph cap) is a constructor option here, not a Protocol change.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def routes(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        departure: datetime,
        load_lb: int,
        max_alternatives: int = 2,
        via: Sequence[LatLon] = (),
        relaxed: bool = False,
    ) -> list[RouteOption]:
        raise NotImplementedError("TomTom routing is implemented in plan phase 3.")
