from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField


class ManualDocument(models.Model):
    """An uploaded maintenance manual (PDF), split into page-aware chunks for search."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="manuals/")
    aircraft_model = models.CharField(max_length=64, blank=True)  # optional scope, e.g. "TB2"
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    page_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    sha256 = models.CharField(max_length=64, unique=True)  # same file uploaded twice → rejected
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.title


class DocumentChunk(models.Model):
    """
    A passage of one page. Chunks never cross page boundaries, so every
    search hit maps to exactly one page number for the citation.
    """

    document = models.ForeignKey(ManualDocument, on_delete=models.CASCADE, related_name="chunks")
    page = models.PositiveIntegerField()  # 1-based, as printed in PDF viewers
    index = models.PositiveIntegerField()  # order within the page
    text = models.TextField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM)

    class Meta:
        ordering = ["document", "page", "index"]
        indexes = [
            # Approximate nearest-neighbour index for cosine distance (pgvector HNSW).
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    def __str__(self) -> str:
        return f"{self.document} p.{self.page}#{self.index}"


class AIRequestLog(models.Model):
    """Who asked the AI what, which provider answered, and how long it took (governance)."""

    feature = models.CharField(max_length=32)  # rag | query | anomaly
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=64, blank=True)
    question = models.TextField()
    degraded = models.BooleanField(default=False)  # True = LLM failed, deterministic fallback used
    latency_ms = models.PositiveIntegerField()
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.feature} by {self.user_id} via {self.provider}"
