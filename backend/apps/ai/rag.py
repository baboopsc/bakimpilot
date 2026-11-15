"""
RAG assistant over maintenance manuals (D-024).

  ingest:  PDF ─▶ text per page ─▶ overlapping chunks (never across pages)
           ─▶ embeddings ─▶ pgvector column (HNSW index)
  ask:     question ─▶ embedding ─▶ top-k nearest chunks (cosine distance)
           ─▶ LLM answers ONLY from those numbered sources, citing [n]
           ─▶ [n] mapped back to (document, page)

Citations are validated: a [n] the model invents that wasn't in the sources
is dropped, so every citation shown points at a real page.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from django.db import transaction
from pgvector.django import CosineDistance
from pypdf import PdfReader

from .models import DocumentChunk, ManualDocument
from .providers import LLMUnavailable, get_embedder, get_llm, tokenize

CHUNK_CHARS = 900
OVERLAP_CHARS = 150
TOP_K = 6
MIN_SIMILARITY = 0.12  # below this the best hit is "not really about the question"


# --- ingestion ---------------------------------------------------------------


def split_page(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split one page into overlapping windows, preferring to cut at line/sentence ends."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def ingest(document: ManualDocument) -> int:
    """Extract, chunk, embed and store. Idempotent: re-ingesting replaces old chunks."""
    document.status = ManualDocument.Status.PROCESSING
    document.save(update_fields=["status"])
    try:
        document.file.open("rb")
        reader = PdfReader(io.BytesIO(document.file.read()))
        document.file.close()
        rows: list[tuple[int, int, str]] = []
        for page_no, page in enumerate(reader.pages, start=1):
            for i, chunk in enumerate(split_page(page.extract_text() or "")):
                rows.append((page_no, i, chunk))
        if not rows:
            raise ValueError("No extractable text (scanned PDF? OCR is not supported yet).")

        embedder = get_embedder()
        vectors: list[list[float]] = []
        for batch_start in range(0, len(rows), 64):
            batch = rows[batch_start : batch_start + 64]
            # Embed title + text so a chunk also matches on the manual's subject.
            vectors += embedder.embed([f"{document.title}\n{text}" for _, _, text in batch])

        with transaction.atomic():
            document.chunks.all().delete()
            DocumentChunk.objects.bulk_create(
                DocumentChunk(document=document, page=p, index=i, text=t, embedding=v)
                for (p, i, t), v in zip(rows, vectors, strict=True)
            )
            document.page_count = len(reader.pages)
            document.status = ManualDocument.Status.READY
            document.error = ""
            document.save(update_fields=["page_count", "status", "error"])
        return len(rows)
    except Exception as exc:
        document.status = ManualDocument.Status.FAILED
        document.error = str(exc)[:2000]
        document.save(update_fields=["status", "error"])
        raise


# --- retrieval ---------------------------------------------------------------


@dataclass
class Source:
    n: int
    chunk_id: int
    document_id: int
    title: str
    page: int
    text: str
    similarity: float


def search(question: str, *, k: int = TOP_K, aircraft_model: str | None = None) -> list[Source]:
    [qvec] = get_embedder().embed([question])
    qs = DocumentChunk.objects.filter(document__status=ManualDocument.Status.READY)
    if aircraft_model:
        qs = qs.filter(document__aircraft_model__in=["", aircraft_model])
    hits = (
        qs.select_related("document")
        .annotate(distance=CosineDistance("embedding", qvec))
        .order_by("distance")[:k]
    )
    return [
        Source(n, h.pk, h.document_id, h.document.title, h.page, h.text, round(1 - float(h.distance), 4))
        for n, h in enumerate(hits, start=1)
    ]


# --- answering ---------------------------------------------------------------

SYSTEM_PROMPT = """You are the maintenance documentation assistant of BakımPilot, used by UAV \
maintenance technicians and planners.

Answer ONLY from the numbered manual excerpts provided. After each statement, cite the excerpt it \
came from as [n]. Quote limits, torque values, part numbers and intervals exactly as written. If \
the excerpts don't contain the answer, say clearly that the uploaded manuals don't cover it; never \
fill gaps from general knowledge, because a wrong number in maintenance can make an aircraft unsafe. \
Answer in the language of the question. Be concise: a short answer, then steps as a list if the \
excerpts give a procedure."""

NOT_FOUND = "I couldn't find this in the uploaded manuals."
STOPWORDS = {
    "the",
    "for",
    "and",
    "what",
    "which",
    "how",
    "with",
    "from",
    "this",
    "that",
    "are",
    "is",
    "bir",
    "ve",
    "ile",
    "için",
    "nedir",
    "nasıl",
    "hangi",
    "kaç",
    "mı",
    "mi",
    "ne",
}


@dataclass
class Answer:
    answer: str
    citations: list[dict] = field(default_factory=list)
    provider: str = "mock"
    model: str = ""
    degraded: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def _prompt(question: str, sources: list[Source]) -> str:
    blocks = "\n\n".join(
        f'<excerpt n="{s.n}" document="{s.title}" page="{s.page}">\n{s.text}\n</excerpt>' for s in sources
    )
    return f"{blocks}\n\nQuestion: {question}"


def _citations(text: str, sources: list[Source]) -> list[dict]:
    by_n = {s.n: s for s in sources}
    used = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text)} & by_n.keys())
    return [
        {
            "n": n,
            "document_id": by_n[n].document_id,
            "title": by_n[n].title,
            "page": by_n[n].page,
            "snippet": by_n[n].text[:280],
        }
        for n in used
    ]


def extractive_answer(question: str, sources: list[Source]) -> str:
    """
    Deterministic answer (mock provider / fallback): the sentences from the
    best excerpts that share the most words with the question, each cited.
    """
    # Compare 5-letter prefixes: a crude stemmer, so "torque" matches "torqued".
    q = {w[:5] for w in tokenize(question) if len(w) > 2 and w not in STOPWORDS}
    scored = []
    for s in sources[:3]:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", s.text):
            words = {w[:5] for w in tokenize(sentence) if w not in STOPWORDS}
            overlap = len(q & words)
            if overlap and len(sentence) > 15:
                scored.append((overlap, s.similarity, s.n, sentence.strip()))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    picked, seen = [], set()
    for _, _, n, sentence in scored:
        if sentence not in seen:
            picked.append(f"{sentence} [{n}]")
            seen.add(sentence)
        if len(picked) == 4:
            break
    return "\n".join(picked) if picked else NOT_FOUND


def answer(question: str, *, aircraft_model: str | None = None) -> Answer:
    sources = search(question, aircraft_model=aircraft_model)
    relevant = [s for s in sources if s.similarity >= MIN_SIMILARITY]
    if not relevant:
        return Answer(NOT_FOUND, provider=get_llm().name)

    llm = get_llm()
    if not llm.is_mock:
        try:
            result = llm.complete(system=SYSTEM_PROMPT, prompt=_prompt(question, relevant), max_tokens=4000)
            return Answer(
                result.text,
                _citations(result.text, relevant),
                provider=llm.name,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        except LLMUnavailable:
            text = extractive_answer(question, relevant)
            return Answer(text, _citations(text, relevant), provider=llm.name, degraded=True)

    text = extractive_answer(question, relevant)
    return Answer(text, _citations(text, relevant), provider="mock")
