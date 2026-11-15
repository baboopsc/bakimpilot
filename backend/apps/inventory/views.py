from django.db.models import F
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.audit.services import record
from apps.workorders.models import WorkOrder

from . import services
from .models import SparePart, StockMovement


class SparePartSerializer(serializers.ModelSerializer):
    is_low = serializers.BooleanField(read_only=True)

    class Meta:
        model = SparePart
        fields = [
            "id",
            "part_number",
            "name",
            "unit",
            "location",
            "quantity_on_hand",
            "min_quantity",
            "is_low",
        ]
        read_only_fields = ["quantity_on_hand"]


class StockMovementSerializer(serializers.ModelSerializer):
    part_number = serializers.CharField(source="part.part_number", read_only=True)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)
    actor = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "part",
            "part_number",
            "delta",
            "balance_after",
            "reason",
            "work_order",
            "work_order_number",
            "note",
            "actor",
            "created_at",
        ]


class QuantitySerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class IssueSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all())


class SparePartViewSet(viewsets.ModelViewSet):
    queryset = SparePart.objects.all()
    serializer_class = SparePartSerializer
    search_fields = ["part_number", "name", "location"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_roles = {"issue": {Role.TECHNICIAN}}

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("low") == "true":
            qs = qs.filter(quantity_on_hand__lte=F("min_quantity"))
        return qs

    def perform_create(self, serializer):
        part = serializer.save()
        record(self.request.user, "stock.part_created", part, f"Created spare part {part}")

    def perform_update(self, serializer):
        part = serializer.save()
        record(self.request.user, "stock.part_updated", part, f"Updated {part}", **serializer.validated_data)

    def _done(self, part, code=status.HTTP_200_OK):
        part.refresh_from_db()
        return Response(SparePartSerializer(part).data, status=code)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        data = QuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        part = self.get_object()
        services.receive(
            actor=request.user,
            part=part,
            quantity=data.validated_data["quantity"],
            note=data.validated_data["note"],
        )
        return self._done(part)

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        data = QuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        part = self.get_object()
        services.adjust(
            actor=request.user,
            part=part,
            delta=data.validated_data["quantity"],
            note=data.validated_data["note"],
        )
        return self._done(part)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        data = IssueSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        part = self.get_object()
        services.issue_to_work_order(
            actor=request.user,
            part=part,
            quantity=data.validated_data["quantity"],
            work_order=data.validated_data["work_order"],
        )
        return self._done(part)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related("part", "work_order", "actor")
    serializer_class = StockMovementSerializer
    filterset_fields = ["part", "work_order", "reason"]
