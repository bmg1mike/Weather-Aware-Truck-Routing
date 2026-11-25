"""Error types and the single error envelope: ``{"error": {"code": "...", "message": "..."}}``.

Every failure path (DRF exceptions, our own ``ApiError``s, Django 404/500) is rendered through
``error_body`` so the frontend only ever parses one shape.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


class ApiError(Exception):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    default_message: str = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def headers(self) -> dict[str, str]:
        return {}

    def extra(self) -> dict[str, Any]:
        """Top-level fields sent alongside ``error`` (rarely needed)."""
        return {}


class ValidationFailed(ApiError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_error"
    default_message = "The request is invalid."


class ProviderUnavailable(ApiError):
    """A provider timed out (after one retry) or returned an unusable response."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "provider_unavailable"

    def __init__(self, provider: str, message: str | None = None) -> None:
        self.provider = provider
        super().__init__(message or f"{provider} did not respond in time. Please try again.")


def human_wait(seconds: int) -> str:
    """``37632`` -> ``"10 hours"``: retry hints in units a driver reads at a glance."""
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes"
    hours = round(seconds / 3600)
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


class ProviderRateLimited(ApiError):
    """A provider answered HTTP 429. Mapped to 503 with a retry hint (spec section 10)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "provider_rate_limited"

    def __init__(self, provider: str, retry_after_s: int = 60) -> None:
        self.provider = provider
        self.retry_after_s = retry_after_s
        super().__init__(f"{provider} is busy. Please retry in about {human_wait(retry_after_s)}.")

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after_s)}


class WeatherRateLimited(ProviderRateLimited):
    """Open-Meteo rate-limited the server's IP address (shared on free hosting).

    The response names the forecasts still needed (``weather_request``) so the browser can fetch
    them from its own address and repeat the request with them (``forecasts``).
    """

    def __init__(
        self, retry_after_s: int, cells: list[tuple[float, float]], start_hour: str, end_hour: str
    ) -> None:
        super().__init__("Open-Meteo", retry_after_s)
        self.weather_request = {"cells": cells, "start_hour": start_hour, "end_hour": end_hour}

    def extra(self) -> dict[str, Any]:
        return {"weather_request": self.weather_request}


class NoRouteFound(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "no_route"
    default_message = "No truck route was found between these places."


class BudgetExceeded(ApiError):
    """The trip needs more weather locations than the free-tier budget allows (spec section 5)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "budget_exceeded"


class NotImplementedYet(ApiError):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = "not_implemented"
    default_message = "This endpoint is not implemented yet."


def _first_validation_message(detail: Any, path: str = "") -> str:
    """Flatten DRF's nested validation detail into its first error, e.g. ``origin.lat: ...``."""
    if isinstance(detail, dict) and detail:
        key, value = next(iter(detail.items()))
        if key != "non_field_errors":
            path = f"{path}.{key}" if path else str(key)
        return _first_validation_message(value, path)
    if isinstance(detail, list) and detail:
        return _first_validation_message(detail[0], path)
    return f"{path}: {detail}" if path else str(detail)


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """DRF ``EXCEPTION_HANDLER``: render every failure in the error envelope."""
    if isinstance(exc, ApiError):
        return Response(
            {**error_body(exc.code, exc.message), **exc.extra()},
            status=exc.status_code,
            headers=exc.headers(),
        )
    # Mirror DRF's default handler: Django's own 404/403 become their DRF equivalents.
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()
    if isinstance(exc, drf_exceptions.APIException):
        if isinstance(exc, drf_exceptions.ValidationError):
            code = ValidationFailed.code
        else:
            codes = exc.get_codes()
            code = codes if isinstance(codes, str) else exc.default_code
        return Response(
            error_body(code, _first_validation_message(exc.detail)), status=exc.status_code
        )
    logger.exception("Unhandled API error", exc_info=exc)
    return Response(
        error_body(ApiError.code, ApiError.default_message),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def bad_request_view(request: HttpRequest, exception: Exception) -> JsonResponse:
    """Django-level 400s, e.g. a disallowed Host header, raised before DRF runs."""
    return JsonResponse(error_body("bad_request", "Bad request."), status=400)


def forbidden_view(request: HttpRequest, exception: Exception) -> JsonResponse:
    return JsonResponse(error_body("forbidden", "Forbidden."), status=403)


def not_found_view(request: HttpRequest, exception: Exception) -> JsonResponse:
    return JsonResponse(error_body("not_found", "No such endpoint."), status=404)


def server_error_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse(error_body(ApiError.code, ApiError.default_message), status=500)
