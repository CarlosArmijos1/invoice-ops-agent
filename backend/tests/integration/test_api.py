from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from opsagent.api.deps import upload_limiter
from opsagent.api.main import create_app
from opsagent.datagen.records import GroundTruth
from opsagent.settings import Environment, Settings
from tests.integration.scripted import DATA, ScriptedLLM, build_test_container, truth_for

pytestmark = pytest.mark.integration

TOKEN = "s3cret"


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def client(session_factory: sessionmaker[Session], llm: ScriptedLLM) -> Iterator[TestClient]:
    upload_limiter._hits.clear()
    settings = Settings(
        environment=Environment.TEST, admin_token=SecretStr(TOKEN), upload_limit_per_hour=5
    )
    container = build_test_container(session_factory, llm, settings)
    with TestClient(create_app(settings, container)) as test_client:
        yield test_client


def _upload(client: TestClient, llm: ScriptedLLM, truth: GroundTruth) -> dict[str, object]:
    llm.current = truth
    content = (DATA / "invoices" / truth.file).read_bytes()
    response = client.post("/api/invoices", files={"file": (truth.file, content)})
    assert response.status_code == 202, response.text
    body: dict[str, object] = response.json()
    return body


def test_health_checks_the_database(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_upload_is_processed_and_visible_with_its_decision(
    client: TestClient, llm: ScriptedLLM
) -> None:
    truth = truth_for("clean_paid")
    uploaded = _upload(client, llm, truth)

    detail = client.get(f"/api/invoices/{uploaded['invoice_id']}").json()
    assert detail["status"] == "decided"
    assert detail["current_action"] == "auto_approve"
    assert detail["matched_po_number"] == truth.extraction.po_number
    assert detail["decisions"][0]["actor"] == "agent"
    assert detail["llm_calls"][0]["purpose"] == "extract"
    assert [e["event"] for e in detail["events"]] == ["received", "decided"]

    again = _upload(client, llm, truth)
    assert again["created"] is False
    assert again["invoice_id"] == uploaded["invoice_id"]

    file = client.get(f"/api/invoices/{uploaded['invoice_id']}/file")
    assert file.status_code == 200
    assert file.content == (DATA / "invoices" / truth.file).read_bytes()


def test_unsupported_upload_is_rejected(client: TestClient) -> None:
    response = client.post("/api/invoices", files={"file": ("notes.txt", b"hello")})
    assert response.status_code == 415


def test_uploads_are_rate_limited(client: TestClient, llm: ScriptedLLM) -> None:
    pdfs = [truth_for(s) for s in ("clean_paid", "clean_unpaid", "missing_po", "unknown_po")]
    pdfs += [truth_for("amount_mismatch"), truth_for("over_limit")]
    statuses = []
    for truth in pdfs:
        llm.current = truth
        content = (DATA / "invoices" / truth.file).read_bytes()
        statuses.append(
            client.post("/api/invoices", files={"file": (truth.file, content)}).status_code
        )
    assert statuses == [202] * 5 + [429]


def test_review_queue_and_human_decision(client: TestClient, llm: ScriptedLLM) -> None:
    approved = _upload(client, llm, truth_for("clean_unpaid"))
    flagged = _upload(client, llm, truth_for("amount_mismatch"))

    queue = client.get("/api/invoices", params={"needs_review": True}).json()
    assert [item["id"] for item in queue["items"]] == [flagged["invoice_id"]]
    assert "amount_mismatch" in queue["items"][0]["finding_codes"]

    url = f"/api/invoices/{flagged['invoice_id']}/review"
    payload = {"outcome": "rejected", "reviewer": "ana", "note": "Cobro de más."}
    assert client.post(url, json=payload).status_code == 201
    assert client.post(url, json=payload).status_code == 409  # already reviewed
    blocked = client.post(f"/api/invoices/{approved['invoice_id']}/review", json=payload)
    assert blocked.status_code == 409  # auto-approved invoices are not reviewable

    detail = client.get(f"/api/invoices/{flagged['invoice_id']}").json()
    assert detail["approved"] is False
    assert detail["decisions"][-1]["actor"] == "human:ana"
    assert detail["decisions"][-1]["review_outcome"] == "rejected"
    assert client.get("/api/invoices", params={"needs_review": True}).json()["total"] == 0


def test_stats_reflect_decisions_and_cost(client: TestClient, llm: ScriptedLLM) -> None:
    _upload(client, llm, truth_for("clean_unpaid"))
    _upload(client, llm, truth_for("unknown_po"))

    stats = client.get("/api/stats").json()
    assert stats["invoices_total"] == 2
    assert stats["by_action"] == {"auto_approve": 1, "request_info": 1}
    assert stats["auto_approval_rate"] == 0.5
    assert float(stats["total_cost_usd"]) > 0
    assert stats["latency_p50_ms"] is not None


def test_operator_endpoints_require_the_token(client: TestClient, llm: ScriptedLLM) -> None:
    _upload(client, llm, truth_for("clean_unpaid"))
    today = date.today().isoformat()

    assert client.post("/api/reports/daily").status_code == 401
    assert client.post("/api/agent/run").status_code == 401
    built = client.post(
        "/api/reports/daily", params={"day": today}, headers={"X-Admin-Token": TOKEN}
    )
    assert built.status_code == 200
    report = client.get(f"/api/reports/{today}").json()
    assert report["summary"]["processed"] == 1
    assert "Reporte diario" in report["markdown"]
    assert client.get("/api/reports").json()[0]["date"] == today
