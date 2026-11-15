from celery import shared_task

from . import anomaly, rag
from .models import ManualDocument


@shared_task
def ingest_document(document_id: int) -> int:
    """PDF parsing + embedding can take a while, so it runs outside the web request."""
    return rag.ingest(ManualDocument.objects.get(pk=document_id))


@shared_task
def run_anomaly_scan() -> dict:
    return anomaly.sync_anomaly_alerts()
