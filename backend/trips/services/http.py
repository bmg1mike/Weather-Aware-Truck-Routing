"""Provider HTTP calls: per-attempt timeout (client-level), one retry, readable error mapping.

- Timeouts, connection errors and 5xx are retried once, then raise ``ProviderUnavailable`` (502).
- HTTP 429 raises ``ProviderRateLimited`` (503 with a retry hint) immediately.
- Other responses are returned for the caller to interpret.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from trips.errors import ProviderRateLimited, ProviderUnavailable

logger = logging.getLogger(__name__)

PROVIDER_RETRIES = 1
DEFAULT_RETRY_AFTER_S = 60


def _retry_after(response: httpx.Response) -> int:
    try:
        value = int(response.headers.get("Retry-After", ""))
    except ValueError:
        return DEFAULT_RETRY_AFTER_S
    return value if value > 0 else DEFAULT_RETRY_AFTER_S


def provider_get(
    client: httpx.Client, provider: str, url: str, params: Mapping[str, Any]
) -> httpx.Response:
    for attempt in range(PROVIDER_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:  # includes every timeout
            logger.warning("%s request failed (attempt %d): %s", provider, attempt + 1, exc)
            continue
        if response.status_code == 429:
            raise ProviderRateLimited(provider, _retry_after(response))
        if response.status_code >= 500:
            logger.warning(
                "%s returned %d (attempt %d)", provider, response.status_code, attempt + 1
            )
            continue
        return response
    raise ProviderUnavailable(provider)


def json_body(response: httpx.Response, provider: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderUnavailable(provider, f"{provider} sent an unreadable response.") from exc
