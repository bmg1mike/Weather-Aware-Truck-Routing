from typing import Any

import pytest
from rest_framework.test import APIClient

from trips.tests import helpers


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def plan_payload() -> dict[str, Any]:
    return helpers.plan_payload()


@pytest.fixture
def heatmap_payload() -> dict[str, Any]:
    return helpers.heatmap_payload()
