from django.db.models import Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.audit.views import AuditLogSerializer
from config.exceptions import DomainError

from . import services
from .models import ChecklistItem, WorkOrder
from .serializers import (
    AssignSerializer,
    ChecklistUpdateSerializer,
    FromDueItemSerializer,
    PasswordSerializer,
    ReasonSerializer,
    WorkOrderSerializer,
    WorkOrderUpdateSerializer,
)

TECH = {Role.TECHNICIAN}
INSPECTOR = {Role.ADMIN, Role.PLANNER}


class WorkOrderViewSet(viewsets.ModelViewSet):
    queryset = WorkOrder.objects.select_related(
        "aircraft", "assigned_to", "created_by", "tech_signed_by", "inspector_signed_by"
    ).prefetch_related(Prefetch("checklist", queryset=ChecklistItem.objects.select_related("done_by")))
    serializer_class = WorkOrderSerializer
    filterset_fields = ["status", "aircraft", "assigned_to", "priority", "grounding", "rule"]
    search_fields = ["number", "title"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_roles = {
        "start": TECH,
        "checklist_item": TECH,
        "sign_off": TECH,
        "certify": INSPECTOR,
        "reject": INSPECTOR,
        "cancel": INSPECTOR,
        "assign": INSPECTOR,
        "from_due_item": INSPECTOR,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("mine") == "true":
            qs = qs.filter(assigned_to=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action == "partial_update":
            return WorkOrderUpdateSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        serializer.instance = services.create_work_order(
            actor=self.request.user, checklist=data.pop("checklist_items", None), **data
        )

    def perform_update(self, serializer):
        if serializer.instance.status in {WorkOrder.Status.CLOSED, WorkOrder.Status.CANCELLED}:
            raise DomainError("Closed or cancelled work orders can't be edited.", "locked")
        wo = serializer.save()
        record(
            self.request.user, "workorder.updated", wo, f"Updated {wo.number}", **serializer.validated_data
        )

    def partial_update(self, request, *args, **kwargs):
        super().partial_update(request, *args, **kwargs)
        return self._out(self.get_object())

    def _out(self, wo, code=status.HTTP_200_OK):
        return Response(WorkOrderSerializer(self.get_queryset().get(pk=wo.pk)).data, status=code)

    def _valid(self, serializer_class):
        s = serializer_class(data=self.request.data)
        s.is_valid(raise_exception=True)
        return s.validated_data

    @action(detail=False, methods=["post"], url_path="from-due-item")
    def from_due_item(self, request):
        data = self._valid(FromDueItemSerializer)
        wo = services.create_from_due_item(
            actor=request.user, key=data["key"], assigned_to=data.get("assigned_to")
        )
        return self._out(wo, status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        data = self._valid(AssignSerializer)
        return self._out(
            services.assign(actor=request.user, wo=self.get_object(), technician=data["technician"])
        )

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._out(services.start(actor=request.user, wo=self.get_object()))

    @action(detail=True, methods=["post"], url_path="checklist")
    def checklist_item(self, request, pk=None):
        data = self._valid(ChecklistUpdateSerializer)
        wo = self.get_object()
        services.set_checklist_item(
            actor=request.user, wo=wo, item_id=data["item"], done=data["done"], note=data["note"]
        )
        return self._out(wo)

    @action(detail=True, methods=["post"], url_path="sign-off")
    def sign_off(self, request, pk=None):
        data = self._valid(PasswordSerializer)
        return self._out(
            services.tech_sign_off(actor=request.user, wo=self.get_object(), password=data["password"])
        )

    @action(detail=True, methods=["post"])
    def certify(self, request, pk=None):
        data = self._valid(PasswordSerializer)
        return self._out(
            services.certify(actor=request.user, wo=self.get_object(), password=data["password"])
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        data = self._valid(ReasonSerializer)
        return self._out(services.reject(actor=request.user, wo=self.get_object(), reason=data["reason"]))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        data = self._valid(ReasonSerializer)
        return self._out(services.cancel(actor=request.user, wo=self.get_object(), reason=data["reason"]))

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Full audit trail for this work order."""
        entries = AuditLog.objects.filter(entity_type="WorkOrder", entity_id=str(pk)).select_related("actor")
        return Response(AuditLogSerializer(entries.order_by("timestamp"), many=True).data)

    @action(detail=True, methods=["get"])
    def verify(self, request, pk=None):
        """Recompute signature hashes: has anything changed since signing?"""
        wo = self.get_object()
        return Response({"number": wo.number, "signatures_valid": services.verify_signatures(wo)})
