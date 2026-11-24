"""Every failure renders as {"error": {"code", "message"}}."""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import Client, override_settings
from rest_framework.exceptions import ValidationError

from trips.errors import (
    NotImplementedYet,
    ProviderRateLimited,
    ProviderUnavailable,
    api_exception_handler,
)


def assert_envelope(body, code):
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_provider_timeout_maps_to_502():
    response = api_exception_handler(ProviderUnavailable("TomTom"), {})
    assert response is not None
    assert response.status_code == 502
    assert_envelope(response.data, "provider_unavailable")
    assert "TomTom" in response.data["error"]["message"]


def test_rate_limit_maps_to_503_with_retry_hint():
    response = api_exception_handler(ProviderRateLimited("Open-Meteo", retry_after_s=60), {})
    assert response is not None
    assert response.status_code == 503
    assert response["Retry-After"] == "60"
    assert_envelope(response.data, "provider_rate_limited")
    assert "retry" in response.data["error"]["message"].lower()


def test_not_implemented_maps_to_501():
    response = api_exception_handler(NotImplementedYet(), {})
    assert response is not None
    assert response.status_code == 501
    assert_envelope(response.data, "not_implemented")


def test_nested_validation_detail_is_flattened_to_one_message():
    exc = ValidationError({"origin": {"lat": ["Ensure this value is less than or equal to 90."]}})
    response = api_exception_handler(exc, {})
    assert response is not None
    assert response.status_code == 400
    assert_envelope(response.data, "validation_error")
    assert response.data["error"]["message"].startswith("origin.lat:")


def test_unexpected_exception_is_a_generic_500():
    response = api_exception_handler(RuntimeError("secret internals"), {})
    assert response is not None
    assert response.status_code == 500
    assert_envelope(response.data, "internal_error")
    assert "secret" not in response.data["error"]["message"]


def test_unknown_route_is_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert_envelope(response.json(), "not_found")


def test_wrong_method_uses_envelope(client):
    response = client.get("/api/trips/plan")
    assert response.status_code == 405
    assert_envelope(response.json(), "method_not_allowed")


def test_malformed_json_uses_envelope(client):
    response = client.post("/api/trips/plan", data="{not json", content_type="application/json")
    assert response.status_code == 400
    assert_envelope(response.json(), "parse_error")


def test_django_404_and_403_from_views_keep_their_status():
    not_found = api_exception_handler(Http404(), {})
    forbidden = api_exception_handler(PermissionDenied(), {})
    assert (not_found.status_code, not_found.data["error"]["code"]) == (404, "not_found")
    assert (forbidden.status_code, forbidden.data["error"]["code"]) == (403, "permission_denied")


@override_settings(ALLOWED_HOSTS=["api.example.com"])
def test_disallowed_host_uses_envelope():
    response = Client().get("/api/health", HTTP_HOST="evil.example.com")
    assert response.status_code == 400
    assert_envelope(response.json(), "bad_request")
