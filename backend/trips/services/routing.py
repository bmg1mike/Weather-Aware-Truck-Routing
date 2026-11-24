"""Routing provider interface and TomTom client (spec section 5, phase 0 findings).

TomTom Routing API v1 ``calculateRoute`` with ``travelMode=truck``, ``vehicleWeight``, ``departAt``
and ``maxAlternatives=2``: one request returns up to three routes. ``progress`` (requested with
``extendedRouteRepresentation=travelTime``) gives cumulative travel time at sparse points, which
is interpolated to every point so checkpoint ETAs follow the provider's timing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from datetime import timezone as dt_timezone
from itertools import pairwise
from typing import Any, Protocol

import httpx
from django.core.cache.backends.base import BaseCache
from django.utils import timezone as dj_timezone

from trips.domain import LatLon, RouteOption
from trips.errors import NoRouteFound, ProviderUnavailable
from trips.services.http import json_body, provider_get
from trips.services.sampling import cumulative_miles

logger = logging.getLogger(__name__)

PROVIDER = "TomTom"
ROUTING_URL = "https://api.tomtom.com/routing/1/calculateRoute"
CACHE_TTL_S = 30 * 60
LB_TO_KG = 0.45359237
M_PER_MI = 1609.344
# TomTom rejects departAt in the past; anything this close to now is sent as "now".
DEPART_NOW_MARGIN = timedelta(minutes=1)
NO_ROUTE_CODES = frozenset({"NO_ROUTE_FOUND", "MAP_MATCHING_FAILURE", "CANNOT_RESTORE_BASEROUTE"})


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
        Raises ``ProviderUnavailable`` on timeout/bad response, ``ProviderRateLimited`` on 429 and
        ``NoRouteFound`` when the provider has no route.
        """
        ...


def _point_offsets(
    points: Sequence[LatLon], progress: Sequence[Any], duration_s: int
) -> list[float] | None:
    """Seconds from departure at every point, interpolated by distance between anchors."""
    if not progress:
        return None
    anchors = {0: 0.0, len(points) - 1: float(duration_s)}
    for entry in progress:
        index = int(entry["pointIndex"])
        if 0 <= index < len(points):
            anchors[index] = float(entry["travelTimeInSeconds"])
    cumulative = cumulative_miles(points)
    ordered = sorted(anchors.items())
    offsets = [0.0] * len(points)
    for (i0, t0), (i1, t1) in pairwise(ordered):
        span = cumulative[i1] - cumulative[i0]
        for i in range(i0, i1 + 1):
            frac = (cumulative[i] - cumulative[i0]) / span if span > 0 else 0.0
            offsets[i] = t0 + (t1 - t0) * frac
    return offsets


def _parse_route(raw: Any) -> dict[str, Any]:
    """Provider-independent, cacheable form of one TomTom route."""
    summary = raw["summary"]
    duration_s = int(summary["travelTimeInSeconds"])
    raw_points = [
        LatLon(float(p["latitude"]), float(p["longitude"]))
        for leg in raw["legs"]
        for p in leg["points"]
    ]
    if len(raw_points) < 2:
        raise ValueError("route has fewer than two points")
    offsets = _point_offsets(raw_points, raw.get("progress") or [], duration_s)
    # Consecutive legs repeat the junction point; drop the repeats (and their offsets).
    keep = [i for i, p in enumerate(raw_points) if i == 0 or p != raw_points[i - 1]]
    arrival = datetime.fromisoformat(summary["arrivalTime"])
    return {
        "points": [(raw_points[i].lat, raw_points[i].lon) for i in keep],
        "offsets": None if offsets is None else [offsets[i] for i in keep],
        "length_m": float(summary["lengthInMeters"]),
        "duration_s": duration_s,
        # The destination's UTC offset, so arrival is shown in local time there.
        "arrival_utc_offset_s": int((arrival.utcoffset() or timedelta(0)).total_seconds()),
    }


def _to_option(index: int, parsed: dict[str, Any], departure: datetime) -> RouteOption:
    duration = timedelta(seconds=parsed["duration_s"])
    destination_tz = dt_timezone(timedelta(seconds=parsed["arrival_utc_offset_s"]))
    return RouteOption(
        id=f"r{index + 1}",
        points=tuple(LatLon(lat, lon) for lat, lon in parsed["points"]),
        distance_mi=parsed["length_m"] / M_PER_MI,
        duration_s=parsed["duration_s"],
        departure=departure,
        arrival=(departure + duration).astimezone(destination_tz),
        point_offsets_s=None if parsed["offsets"] is None else tuple(parsed["offsets"]),
    )


class TomTomRoutingProvider:
    """Holds the server-side key; never expose it to the client."""

    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        cache: BaseCache,
        *,
        url: str = ROUTING_URL,
        ttl_s: int = CACHE_TTL_S,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._cache = cache
        self._url = url
        self._ttl_s = ttl_s

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
        if relaxed:
            raise NotImplementedError("Relaxed alternatives are part of plan phase 6.")
        locations = [origin, *via, destination]
        hour = departure.astimezone(UTC).strftime("%Y%m%dT%H")
        key = "route:v1:" + ":".join(
            [
                *(f"{p.lat:.5f},{p.lon:.5f}" for p in locations),
                hour,
                str(load_lb),
                str(max_alternatives),
            ]
        )
        parsed: list[dict[str, Any]] | None = self._cache.get(key)
        if parsed is None:
            parsed = self._fetch(locations, departure, load_lb, max_alternatives)
            self._cache.set(key, parsed, timeout=self._ttl_s)
        return [_to_option(i, route, departure) for i, route in enumerate(parsed)]

    def _fetch(
        self, locations: Sequence[LatLon], departure: datetime, load_lb: int, max_alternatives: int
    ) -> list[dict[str, Any]]:
        path = ":".join(f"{p.lat},{p.lon}" for p in locations)
        depart_at = (
            "now" if departure <= dj_timezone.now() + DEPART_NOW_MARGIN else departure.isoformat()
        )
        params = {
            "key": self._api_key,
            "travelMode": "truck",
            "vehicleCommercial": "true",
            "vehicleWeight": round(load_lb * LB_TO_KG),
            "maxAlternatives": max_alternatives,
            "departAt": depart_at,
            "routeType": "fastest",
            "traffic": "true",
            "extendedRouteRepresentation": ["distance", "travelTime"],
        }
        response = provider_get(self._client, PROVIDER, f"{self._url}/{path}/json", params)
        if response.status_code != 200:
            raise self._error(response)
        body = json_body(response, PROVIDER)
        try:
            routes = [_parse_route(raw) for raw in body.get("routes") or []]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(
                PROVIDER, "TomTom sent an unexpected route response."
            ) from exc
        if not routes:
            raise NoRouteFound()
        return routes

    @staticmethod
    def _error(response: httpx.Response) -> Exception:
        try:
            code = (response.json().get("detailedError") or {}).get("code")
        except (ValueError, AttributeError):
            code = None
        # Log the status and error code only: error bodies may echo request details.
        logger.warning("TomTom routing returned %d (%s)", response.status_code, code)
        if response.status_code == 400 and code in NO_ROUTE_CODES:
            return NoRouteFound()
        if response.status_code in (401, 403):
            return ProviderUnavailable(
                PROVIDER, "Routing is unavailable: the TomTom key was rejected."
            )
        return ProviderUnavailable(PROVIDER, "TomTom could not plan this route. Please try again.")
