from typing import Any

import httpx
import pytest
from rest_framework.test import APIClient

from trips.services import container
from trips.tests import helpers


@pytest.fixture(autouse=True)
def no_real_provider_calls(monkeypatch):
    """Any test that reaches a real provider client fails instead of calling the internet."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected provider call in tests: {request.url.host}")

    monkeypatch.setattr(
        container, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def plan_payload() -> dict[str, Any]:
    return helpers.plan_payload()


@pytest.fixture
def heatmap_payload() -> dict[str, Any]:
    return helpers.heatmap_payload()
