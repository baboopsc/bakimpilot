"""
Thin views: they validate input with a serializer, call a service function,
and serialise the result. No business rules live here (D-007).
"""

import hmac

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.audit.services import record

from . import services
from .models import Aircraft, Component, FlightLog, Installation, PartType
from .serializers import (
    AircraftSerializer,
    ComponentSerializer,
    FlightLogSerializer,
    InstallationSerializer,
    InstallSerializer,
    PartTypeSerializer,
    RemoveSerializer,
)

OPEN_INSTALLS = Prefetch(
    "installations",
    queryset=Installation.objects.filter(removed_at__isnull=True).select_related("aircraft"),
)


class AircraftViewSet(viewsets.ModelViewSet):
    queryset = Aircraft.objects.all()
    serializer_class = AircraftSerializer
    filterset_fields = ["status", "model"]
    search_fields = ["tail_number", "serial_number"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # retire instead of delete

    def perform_create(self, serializer):
        serializer.instance = services.create_aircraft(actor=self.request.user, **serializer.validated_data)

    def perform_update(self, serializer):
        aircraft = serializer.save()
        record(
            self.request.user,
            "aircraft.updated",
            aircraft,
            f"Updated {aircraft}",
            **serializer.validated_data,
        )

    @action(detail=True, methods=["get"])
    def components(self, request, pk=None):
        """What is installed on this aircraft right now."""
        installs = (
            Installation.objects.filter(aircraft_id=pk, removed_at__isnull=True)
            .select_related("component__part_type", "aircraft")
            .order_by("position")
        )
        return Response(InstallationSerializer(installs, many=True).data)


class PartTypeViewSet(viewsets.ModelViewSet):
    queryset = PartType.objects.all()
    serializer_class = PartTypeSerializer
    search_fields = ["part_number", "name"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        pt = serializer.save()
        record(self.request.user, "part_type.created", pt, f"Created part type {pt}")

    def perform_update(self, serializer):
        pt = serializer.save()
        record(
            self.request.user, "part_type.updated", pt, f"Updated part type {pt}", **serializer.validated_data
        )


class ComponentViewSet(viewsets.ModelViewSet):
    queryset = Component.objects.select_related("part_type").prefetch_related(OPEN_INSTALLS)
    serializer_class = ComponentSerializer
    filterset_fields = ["status", "part_type", "installations__aircraft"]
    search_fields = ["serial_number", "part_type__part_number", "part_type__name"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        serializer.instance = services.create_component(actor=self.request.user, **serializer.validated_data)

    def perform_update(self, serializer):
        component = serializer.save()
        record(
            self.request.user,
            "component.updated",
            component,
            f"Updated {component}",
            **serializer.validated_data,
        )

    def _fresh(self, pk):
        return self.get_queryset().get(pk=pk)

    @action(detail=True, methods=["post"])
    def install(self, request, pk=None):
        data = InstallSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.install_component(
            actor=request.user,
            component=self.get_object(),
            aircraft=data.validated_data["aircraft"],
            position=data.validated_data["position"],
            at=data.validated_data.get("installed_at"),
        )
        return Response(ComponentSerializer(self._fresh(pk)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        data = RemoveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.remove_component(
            actor=request.user,
            component=self.get_object(),
            reason=data.validated_data["reason"],
            at=data.validated_data.get("removed_at"),
            mark_unserviceable=data.validated_data["mark_unserviceable"],
        )
        return Response(ComponentSerializer(self._fresh(pk)).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        installs = Installation.objects.filter(component_id=pk).select_related(
            "aircraft", "component__part_type"
        )
        return Response(InstallationSerializer(installs, many=True).data)


class InstallationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Installation.objects.select_related("aircraft", "component__part_type")
    serializer_class = InstallationSerializer
    filterset_fields = ["aircraft", "component", "position"]


class FlightLogViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    Flights can be created and read but not edited or deleted through the API:
    they drive component life, so silent edits would corrupt it (D-013).
    """

    queryset = FlightLog.objects.select_related("aircraft", "logged_by")
    serializer_class = FlightLogSerializer
    filterset_fields = {"aircraft": ["exact"], "takeoff_at": ["gte", "lte"], "source": ["exact"]}
    write_roles = {Role.ADMIN, Role.PLANNER, Role.TECHNICIAN}

    def perform_create(self, serializer):
        serializer.instance = services.log_flight(actor=self.request.user, **serializer.validated_data)


# --- machine-to-machine ingestion (D-033) ---------------------------------------


class IngestFlightSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=64)
    tail_number = serializers.CharField(max_length=32)
    takeoff_at = serializers.DateTimeField()
    landing_at = serializers.DateTimeField()
    cycles = serializers.IntegerField(min_value=1, default=1)
    max_engine_temp_c = serializers.DecimalField(
        max_digits=6, decimal_places=1, required=False, allow_null=True
    )
    avg_vibration_g = serializers.DecimalField(
        max_digits=6, decimal_places=3, required=False, allow_null=True
    )
    fuel_used_l = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)
    mission = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")


class IngestFlightView(APIView):
    """
    POST /api/ingest/flights/ from the flight-data ingestion service.

    Authenticated with a shared service token (X-Ingest-Token), not a user
    JWT: this is a machine, and it may only create flights. Idempotent on
    `external_id`: the ingest service retries on network errors, and a retry
    of a flight we already stored returns 200 instead of counting the hours twice.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]  # checked below with the service token

    @extend_schema(request=IngestFlightSerializer, responses=FlightLogSerializer)
    def post(self, request):
        expected = settings.INGEST_TOKEN
        given = request.headers.get("X-Ingest-Token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return Response({"detail": "Invalid ingest token."}, status=status.HTTP_401_UNAUTHORIZED)

        data = IngestFlightSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        existing = FlightLog.objects.filter(external_id=v["external_id"]).first()
        if existing:
            return Response(FlightLogSerializer(existing).data, status=status.HTTP_200_OK)
        aircraft = Aircraft.objects.filter(tail_number=v.pop("tail_number")).first()
        if aircraft is None:
            return Response({"detail": "Unknown tail number.", "code": "unknown_aircraft"}, status=400)
        try:
            flight = services.log_flight(actor=None, aircraft=aircraft, source="ingest", **v)
        except IntegrityError:  # two retries raced: the other one stored it
            flight = FlightLog.objects.get(external_id=v["external_id"])
            return Response(FlightLogSerializer(flight).data, status=status.HTTP_200_OK)
        return Response(FlightLogSerializer(flight).data, status=status.HTTP_201_CREATED)
