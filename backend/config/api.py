"""One place that lists every REST resource, so the whole API surface is visible at a glance."""

from rest_framework.routers import DefaultRouter

from apps.accounts.views import UserViewSet
from apps.audit.views import AuditLogViewSet
from apps.fleet.views import (
    AircraftViewSet,
    ComponentViewSet,
    FlightLogViewSet,
    InstallationViewSet,
    PartTypeViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("audit-log", AuditLogViewSet, basename="audit-log")
router.register("aircraft", AircraftViewSet, basename="aircraft")
router.register("part-types", PartTypeViewSet, basename="part-type")
router.register("components", ComponentViewSet, basename="component")
router.register("installations", InstallationViewSet, basename="installation")
router.register("flights", FlightLogViewSet, basename="flight")
