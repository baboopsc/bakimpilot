"""One place that lists every REST resource, so the whole API surface is visible at a glance."""

from rest_framework.routers import DefaultRouter

from apps.accounts.views import UserViewSet
from apps.audit.views import AuditLogViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("audit-log", AuditLogViewSet, basename="audit-log")
