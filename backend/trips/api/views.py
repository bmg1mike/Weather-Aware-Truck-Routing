"""HTTP endpoints. Business logic lives in ``trips.services``; views validate and present."""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from trips.api.presenters import geocode_json, plan_json
from trips.api.serializers import (
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)
from trips.domain import LatLon, Place
from trips.errors import NotImplementedYet
from trips.services.container import get_geocoder, get_planner
from trips.services.planner import PlanInput


class HealthView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeView(APIView):
    def get(self, request: Request) -> Response:
        query = GeocodeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(geocode_json(get_geocoder().search(query.validated_data["q"])))


def _place(data: dict[str, float | str]) -> Place:
    return Place(str(data["label"]), LatLon(float(data["lat"]), float(data["lon"])))


class PlanView(APIView):
    def post(self, request: Request) -> Response:
        serializer = PlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        trip = PlanInput(
            origin=_place(data["origin"]),
            destination=_place(data["destination"]),
            departure=data["departure"],
            load_lb=data["load_lb"],
            interval_mi=data["interval_mi"],
        )
        return Response(plan_json(get_planner().plan(trip)))


class HeatmapView(APIView):
    def post(self, request: Request) -> Response:
        HeatmapRequestSerializer(data=request.data).is_valid(raise_exception=True)
        raise NotImplementedYet("The heatmap arrives in plan phase 5.")
