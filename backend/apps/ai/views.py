import hashlib
import time

from django.db import transaction
from django.http import FileResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.audit.services import record
from apps.fleet.models import Aircraft

from . import anomaly, nlquery, rag
from .models import AIRequestLog, ManualDocument
from .tasks import ingest_document

MAX_PDF_BYTES = 25 * 1024 * 1024


# Asking questions is read-only, so every role may POST to these endpoints.
ANY_ROLE = set(Role.values)


class AIThrottle(UserRateThrottle):
    """LLM calls cost money: cap them per user (D-022)."""

    scope = "ai"
    rate = "30/min"


def _log(request, feature, question, started, result):
    AIRequestLog.objects.create(
        feature=feature,
        user=request.user,
        provider=result.get("provider", ""),
        model=result.get("model", "") or "",
        question=question[:4000],
        degraded=bool(result.get("degraded")),
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=result.get("input_tokens", 0) or 0,
        output_tokens=result.get("output_tokens", 0) or 0,
    )


class ManualDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.CharField(source="uploaded_by.username", read_only=True)
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = ManualDocument
        fields = [
            "id",
            "title",
            "file",
            "aircraft_model",
            "status",
            "page_count",
            "chunk_count",
            "error",
            "uploaded_by",
            "uploaded_at",
        ]
        read_only_fields = ["status", "page_count", "error", "uploaded_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def validate_file(self, f):
        if f.size > MAX_PDF_BYTES:
            raise serializers.ValidationError("PDF is larger than 25 MB.")
        head = f.read(5)
        f.seek(0)
        if head != b"%PDF-":  # check the content, not just the file name
            raise serializers.ValidationError("File is not a PDF.")
        return f


class ManualDocumentViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ManualDocument.objects.select_related("uploaded_by")
    serializer_class = ManualDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        upload = serializer.validated_data["file"]
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        if ManualDocument.objects.filter(sha256=digest.hexdigest()).exists():
            raise serializers.ValidationError({"file": "This PDF has already been uploaded."})
        doc = serializer.save(uploaded_by=self.request.user, sha256=digest.hexdigest())
        record(self.request.user, "manual.uploaded", doc, f"Uploaded manual {doc.title}")
        transaction.on_commit(lambda: ingest_document.delay(doc.pk))

    def perform_destroy(self, instance):
        record(self.request.user, "manual.deleted", instance, f"Deleted manual {instance.title}")
        instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        """Serve the PDF so the UI can open it at the cited page (#page=N)."""
        doc = self.get_object()
        return FileResponse(doc.file.open("rb"), content_type="application/pdf", filename=f"{doc.title}.pdf")

    @action(detail=True, methods=["post"])
    def reingest(self, request, pk=None):
        doc = self.get_object()
        ingest_document.delay(doc.pk)
        doc.refresh_from_db()
        return Response(ManualDocumentSerializer(doc).data, status=status.HTTP_202_ACCEPTED)


class QuestionSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)
    aircraft_model = serializers.CharField(max_length=64, required=False, allow_blank=True)


class AskManualsView(APIView):
    """POST /api/ai/ask/ — answer from uploaded manuals with page citations."""

    throttle_classes = [AIThrottle]
    write_roles = ANY_ROLE

    def post(self, request):
        data = QuestionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        started = time.monotonic()
        ans = rag.answer(
            data.validated_data["question"], aircraft_model=data.validated_data.get("aircraft_model") or None
        )
        result = ans.__dict__
        _log(request, "rag", data.validated_data["question"], started, result)
        return Response(result)


class NLQueryView(APIView):
    """POST /api/ai/query/ — natural-language question over maintenance data (read-only)."""

    throttle_classes = [AIThrottle]
    write_roles = ANY_ROLE

    def post(self, request):
        data = QuestionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        started = time.monotonic()
        result = nlquery.run_query(data.validated_data["question"])
        _log(request, "query", data.validated_data["question"], started, result)
        return Response(result)


class AnomalyListView(APIView):
    """GET /api/ai/anomalies/?aircraft=<id> — statistically unusual flight data (no LLM involved)."""

    def get(self, request):
        aircraft_id = request.query_params.get("aircraft")
        qs = Aircraft.objects.filter(status=Aircraft.Status.ACTIVE)
        if aircraft_id and aircraft_id.isdigit():
            qs = qs.filter(pk=int(aircraft_id))
        found = [a for ac in qs for a in anomaly.detect(ac)]
        return Response([{**a.__dict__, "key": a.key} for a in found])


class ExplainSerializer(serializers.Serializer):
    aircraft = serializers.PrimaryKeyRelatedField(queryset=Aircraft.objects.all())
    metric = serializers.ChoiceField(choices=list(anomaly.METRICS))
    language = serializers.CharField(max_length=20, required=False, allow_blank=True)


class ExplainAnomalyView(APIView):
    """POST /api/ai/anomalies/explain/ — LLM explanation of one detected anomaly."""

    throttle_classes = [AIThrottle]
    write_roles = ANY_ROLE

    def post(self, request):
        data = ExplainSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ac, metric = data.validated_data["aircraft"], data.validated_data["metric"]
        found = next((a for a in anomaly.detect(ac) if a.metric == metric), None)
        if found is None:
            return Response({"detail": "No anomaly currently detected for this metric."}, status=404)
        started = time.monotonic()
        result = anomaly.explain(found, language_hint=data.validated_data.get("language", ""))
        _log(request, "anomaly", f"{ac.tail_number} {metric}", started, result)
        return Response(result)


class AIRequestLogSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.username", default=None)

    class Meta:
        model = AIRequestLog
        fields = "__all__"


class AIRequestLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AIRequestLog.objects.select_related("user")
    serializer_class = AIRequestLogSerializer
    filterset_fields = ["feature", "provider", "degraded"]
    action_roles = {"list": {Role.ADMIN}, "retrieve": {Role.ADMIN}}
