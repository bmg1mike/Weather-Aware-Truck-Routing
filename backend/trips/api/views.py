"""HTTP endpoints. Phase 1: input validation is live; business logic returns 501 until built."""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from trips.api.serializers import (
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)
from trips.errors import NotImplementedYet


class HealthView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeView(APIView):
    def get(self, request: Request) -> Response:
        GeocodeQuerySerializer(data=request.query_params).is_valid(raise_exception=True)
        raise NotImplementedYet("Geocoding arrives in plan phase 3.")


class PlanView(APIView):
    def post(self, request: Request) -> Response:
        PlanRequestSerializer(data=request.data).is_valid(raise_exception=True)
        raise NotImplementedYet("Trip planning arrives in plan phase 3.")


class HeatmapView(APIView):
    def post(self, request: Request) -> Response:
        HeatmapRequestSerializer(data=request.data).is_valid(raise_exception=True)
        raise NotImplementedYet("The heatmap arrives in plan phase 5.")
