from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.ai import anomaly, nlquery, rag
from apps.ai.models import AIRequestLog, ManualDocument
from apps.ai.pdfgen import build_pdf
from apps.ai.providers import AnthropicProvider, HashingEmbedder, LLMProvider, LLMResult, LLMUnavailable
from apps.alerts.models import Alert
from apps.fleet import services as fleet
from apps.fleet.tests.factories import AircraftFactory

MANUAL = [
    [
        "TB2 Engine Maintenance Manual",
        "Chapter 1 General",
        "Always disconnect the battery before engine work.",
    ],
    [
        "Chapter 2 Oil change",
        "Drain the engine oil while warm.",
        "Torque the oil drain plug to 25 Nm and secure with lock wire.",
        "Refill with 3.2 L of 15W-50 oil.",
    ],
    [
        "Chapter 3 Propeller",
        "Maximum allowed propeller vibration is 0.55 g at cruise power.",
        "Balance the propeller dynamically if vibration exceeds the limit.",
    ],
]


class FakeLLM(LLMProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, text="", json=None, fail=False):
        self.text, self.json, self.fail, self.calls = text, json, fail, []

    def complete(self, *, system, prompt, max_tokens=4000):
        self.calls.append(prompt)
        if self.fail:
            raise LLMUnavailable("down")
        return LLMResult(self.text, "fake-model", 10, 5)

    def complete_json(self, *, system, prompt, schema, max_tokens=4000):
        if self.fail:
            raise LLMUnavailable("down")
        return self.json


@pytest.fixture
def manual(db, planner):
    pdf = SimpleUploadedFile("tb2.pdf", build_pdf(MANUAL), content_type="application/pdf")
    doc = ManualDocument.objects.create(
        title="TB2 Engine Manual", file=pdf, sha256="x" * 64, uploaded_by=planner
    )
    rag.ingest(doc)
    return doc


# --- embeddings ------------------------------------------------------------------


def test_hashing_embedder_is_deterministic_normalised_and_lexical():
    e = HashingEmbedder(384)
    a, b, c = e.embed(["oil drain plug torque", "torque for the oil drain plug", "propeller vibration limit"])
    assert a == e.embed(["oil drain plug torque"])[0]
    assert abs(sum(x * x for x in a) - 1) < 1e-9
    cos = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    assert cos(a, b) > cos(a, c)


# --- RAG ---------------------------------------------------------------------------


def test_split_page_overlaps_and_respects_size():
    text = ". ".join(f"Sentence number {i} about maintenance" for i in range(80))
    chunks = rag.split_page(text, size=300, overlap=50)
    assert len(chunks) > 3 and all(len(c) <= 300 for c in chunks)


@pytest.mark.django_db
def test_ingest_keeps_page_numbers(manual):
    assert manual.status == ManualDocument.Status.READY and manual.page_count == 3
    assert set(manual.chunks.values_list("page", flat=True)) == {1, 2, 3}


@pytest.mark.django_db
def test_mock_answer_cites_the_right_page(manual):
    ans = rag.answer("What torque for the oil drain plug?")
    assert "25 Nm" in ans.answer
    assert ans.citations and ans.citations[0]["page"] == 2
    assert ans.provider == "mock"


@pytest.mark.django_db
def test_unrelated_question_says_not_found(manual):
    assert rag.answer("Wi-Fi password for the canteen?").answer == rag.NOT_FOUND


@pytest.mark.django_db
def test_llm_answer_hallucinated_citations_are_dropped(manual, monkeypatch):
    fake = FakeLLM(text="Torque it to 25 Nm [1]. Also see [99].")
    monkeypatch.setattr(rag, "get_llm", lambda: fake)
    ans = rag.answer("oil drain plug torque")
    assert [c["n"] for c in ans.citations] == [1]
    assert "<excerpt" in fake.calls[0] and "25 Nm" in fake.calls[0]  # sources were given to the model
    assert ans.provider == "fake" and not ans.degraded


@pytest.mark.django_db
def test_llm_outage_falls_back_to_extractive(manual, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda: FakeLLM(fail=True))
    ans = rag.answer("oil drain plug torque")
    assert ans.degraded and "25 Nm" in ans.answer


@pytest.mark.django_db
def test_upload_and_ask_over_http(
    planner_client, viewer_client, tech_client, django_capture_on_commit_callbacks
):
    pdf = SimpleUploadedFile("m.pdf", build_pdf(MANUAL), content_type="application/pdf")
    with django_capture_on_commit_callbacks(execute=True):
        res = planner_client.post(
            "/api/ai/documents/", {"title": "TB2 Manual", "file": pdf}, format="multipart"
        )
    assert res.status_code == 201, res.data
    assert planner_client.get(f"/api/ai/documents/{res.data['id']}/").data["status"] == "READY"

    dup = SimpleUploadedFile("again.pdf", build_pdf(MANUAL), content_type="application/pdf")
    assert (
        planner_client.post("/api/ai/documents/", {"title": "x", "file": dup}, format="multipart").status_code
        == 400
    )
    fake = SimpleUploadedFile("evil.pdf", b"MZ not a pdf", content_type="application/pdf")
    assert (
        planner_client.post(
            "/api/ai/documents/", {"title": "x", "file": fake}, format="multipart"
        ).status_code
        == 400
    )
    pdf2 = SimpleUploadedFile("v.pdf", build_pdf([["other"]]), content_type="application/pdf")
    assert (
        viewer_client.post("/api/ai/documents/", {"title": "x", "file": pdf2}, format="multipart").status_code
        == 403
    )

    ans = tech_client.post("/api/ai/ask/", {"question": "max propeller vibration?"}, format="json")
    assert ans.status_code == 200 and "0.55 g" in ans.data["answer"]
    assert ans.data["citations"][0]["page"] == 3
    assert AIRequestLog.objects.filter(feature="rag").count() == 1

    pdf_res = viewer_client.get(f"/api/ai/documents/{res.data['id']}/file/")
    assert pdf_res.status_code == 200 and pdf_res["Content-Type"] == "application/pdf"


# --- Anthropic provider (SDK client stubbed: no network) -------------------------------


def _fake_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        _request_id="req_test",
    )


def _provider_with(response):
    p = AnthropicProvider(api_key="test-key")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return response

    p.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return p, sent


def test_anthropic_provider_request_shape_and_text_extraction():
    p, sent = _provider_with(_fake_response("Answer [1]"))
    result = p.complete(system="sys", prompt="q")
    assert result.text == "Answer [1]" and result.input_tokens == 100
    assert sent["model"] == "claude-opus-5-5"
    assert sent["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in sent["betas"]
    assert "thinking" not in sent and "temperature" not in sent  # not allowed on this model


def test_anthropic_provider_json_and_refusal():
    p, sent = _provider_with(_fake_response('{"entity": "aircraft"}'))
    assert p.complete_json(system="s", prompt="q", schema={"type": "object"}) == {"entity": "aircraft"}
    assert sent["output_config"]["format"]["type"] == "json_schema"

    p, _ = _provider_with(_fake_response("", stop_reason="refusal"))
    with pytest.raises(LLMUnavailable):
        p.complete(system="s", prompt="q")


# --- natural-language query ---------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "entity", "expected"),
    [
        ("Which aircraft are grounded?", "aircraft", {"airworthiness": "GROUNDED"}),
        ("Hangi uçaklar yerde?", "aircraft", {"airworthiness": "GROUNDED"}),
        ("Gecikmiş bakımlar neler?", "due_items", {"status": "OVERDUE"}),
        ("maintenance due in the next 14 days", "due_items", {"within_days": 14}),
        ("TB2-T003 açık iş emirleri", "work_orders", {"open_only": True, "tail_number": "TB2-T003"}),
        ("düşük stoklu yedek parçalar", "spare_parts", {"low_stock": True}),
        ("components with less than 50 hours of life", "components", {"life_remaining_hours_below": 50.0}),
        ("critical alerts", "alerts", {"severity": "CRITICAL"}),
    ],
)
def test_rule_based_parser(question, entity, expected):
    spec = nlquery.rule_based_spec(question)
    assert spec["entity"] == entity
    for k, v in expected.items():
        assert spec["filters"][k] == v


def test_normalise_never_trusts_model_output():
    spec = nlquery.normalise({"entity": "users; DROP TABLE", "filters": {"evil": 1}, "limit": 10**9})
    assert (
        spec["entity"] == "aircraft" and "evil" not in spec["filters"] and spec["limit"] == nlquery.MAX_LIMIT
    )


@pytest.mark.django_db
def test_query_over_http_mock_and_llm(viewer_client, monkeypatch):
    AircraftFactory(tail_number="TB2-T001")
    res = viewer_client.post("/api/ai/query/", {"question": "Hangi uçaklar yerde?"}, format="json")
    assert res.status_code == 200 and res.data["spec"]["entity"] == "aircraft" and res.data["count"] == 0

    spec = {
        "entity": "aircraft",
        "filters": dict.fromkeys(nlquery.FILTERS),
        "limit": 5,
        "explanation": "All aircraft",
    }
    monkeypatch.setattr(nlquery, "get_llm", lambda: FakeLLM(json=spec))
    res = viewer_client.post("/api/ai/query/", {"question": "list everything"}, format="json")
    assert res.data["count"] == 1 and res.data["provider"] == "fake"
    assert res.data["rows"][0]["tail_number"] == "TB2-T001"


# --- anomaly detection --------------------------------------------------------------


def test_robust_z_ignores_baseline_outlier():
    base = [0.40, 0.41, 0.42, 0.43, 0.39, 0.41, 5.0, 0.42, 0.40, 0.41]  # one broken reading
    med, mad, zs = anomaly.robust_z([0.42, 0.70], base)
    assert 0.40 <= med <= 0.42
    assert abs(zs[0]) < 3.5 < zs[1]


def _fly_series(ac, vibrations):
    start = timezone.now() - timedelta(days=len(vibrations) + 1)
    for i, v in enumerate(vibrations):
        t = start + timedelta(days=i)
        fleet.log_flight(
            actor=None,
            aircraft=ac,
            takeoff_at=t,
            landing_at=t + timedelta(hours=2),
            avg_vibration_g=Decimal(str(v)),
            max_engine_temp_c=Decimal("95.0") + Decimal(i % 3),
            fuel_used_l=Decimal("22.0") + Decimal(i % 2),
        )


@pytest.mark.django_db
def test_detects_creeping_vibration_but_not_noise():
    normal = [0.40, 0.42, 0.41, 0.43, 0.39, 0.42, 0.41, 0.40, 0.44, 0.41, 0.42, 0.40]
    noisy, creeping = AircraftFactory(), AircraftFactory()
    _fly_series(noisy, normal + [0.42, 0.41, 0.60, 0.43, 0.40])  # one spike only
    _fly_series(creeping, normal + [0.45, 0.52, 0.58, 0.64, 0.71])

    assert anomaly.detect(noisy) == []
    [found] = anomaly.detect(creeping)
    assert found.metric == "avg_vibration_g" and found.direction == "high" and found.flagged_flights >= 2

    result = anomaly.sync_anomaly_alerts()
    assert result["opened"] == 1
    assert Alert.objects.get(kind=Alert.Kind.ANOMALY).aircraft == creeping
    assert "propeller" in anomaly.explain(found)["explanation"].lower()


@pytest.mark.django_db
def test_not_enough_history_is_not_an_anomaly():
    ac = AircraftFactory()
    _fly_series(ac, [0.4, 0.4, 0.9, 0.9, 0.9])
    assert anomaly.detect(ac) == []


@pytest.mark.django_db
def test_anomaly_endpoints(viewer_client, monkeypatch):
    ac = AircraftFactory()
    _fly_series(
        ac, [0.40, 0.42, 0.41, 0.43, 0.39, 0.42, 0.41, 0.40, 0.44, 0.41, 0.45, 0.52, 0.58, 0.64, 0.71]
    )
    listed = viewer_client.get("/api/ai/anomalies/").data
    assert listed[0]["metric"] == "avg_vibration_g"

    fake = FakeLLM(text="Likely propeller imbalance. Advisory only.")
    monkeypatch.setattr(anomaly, "get_llm", lambda: fake)
    res = viewer_client.post(
        "/api/ai/anomalies/explain/", {"aircraft": ac.pk, "metric": "avg_vibration_g"}, format="json"
    )
    assert res.status_code == 200 and res.data["explanation"].startswith("Likely propeller")
    assert ac.tail_number in fake.calls[0]  # aircraft context was given to the model
    none = viewer_client.post(
        "/api/ai/anomalies/explain/", {"aircraft": ac.pk, "metric": "fuel_per_hour_l"}, format="json"
    )
    assert none.status_code == 404
