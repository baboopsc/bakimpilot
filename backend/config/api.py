"""One place that lists every REST resource, so the whole API surface is visible at a glance."""

from rest_framework.routers import DefaultRouter

from apps.accounts.views import UserViewSet
from apps.ai.views import AIRequestLogViewSet, ManualDocumentViewSet
from apps.alerts.views import AlertViewSet
from apps.audit.views import AuditLogViewSet
from apps.fleet.views import (
    AircraftViewSet,
    ComponentViewSet,
    FlightLogViewSet,
    InstallationViewSet,
    PartTypeViewSet,
)
from apps.inventory.views import SparePartViewSet, StockMovementViewSet
from apps.maintenance.views import MaintenanceRecordViewSet, MaintenanceRuleViewSet
from apps.workorders.views import WorkOrderViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("audit-log", AuditLogViewSet, basename="audit-log")
router.register("aircraft", AircraftViewSet, basename="aircraft")
router.register("part-types", PartTypeViewSet, basename="part-type")
router.register("components", ComponentViewSet, basename="component")
router.register("installations", InstallationViewSet, basename="installation")
router.register("flights", FlightLogViewSet, basename="flight")
router.register("maintenance-rules", MaintenanceRuleViewSet, basename="maintenance-rule")
router.register("maintenance-records", MaintenanceRecordViewSet, basename="maintenance-record")
router.register("alerts", AlertViewSet, basename="alert")
router.register("work-orders", WorkOrderViewSet, basename="work-order")
router.register("spare-parts", SparePartViewSet, basename="spare-part")
router.register("stock-movements", StockMovementViewSet, basename="stock-movement")
router.register("ai/documents", ManualDocumentViewSet, basename="manual")
router.register("ai/logs", AIRequestLogViewSet, basename="ai-log")
