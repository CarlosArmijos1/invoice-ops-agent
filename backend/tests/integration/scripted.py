"""Shared helpers for integration tests: dataset access, a scripted LLM, a test container."""

import json
from datetime import date
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.orm import Session, sessionmaker

from opsagent.agent.deps import AgentDeps
from opsagent.container import Container
from opsagent.datagen.records import GroundTruth
from opsagent.extraction.extractor import InvoiceExtractor
from opsagent.infra.seed import load_catalog, seed_catalog
from opsagent.llm.base import CompletionRequest
from opsagent.llm.fake import FakeLLMClient, Outcome
from opsagent.services.processing import InvoiceProcessor
from opsagent.settings import Environment, Settings

DATA = Path(__file__).resolve().parents[3] / "data" / "synthetic"
TRUTHS = {
    t["file"]: GroundTruth.model_validate(t)
    for t in json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))
}


def truth_for(scenario: str, render: str | None = None) -> GroundTruth:
    return next(
        t for t in TRUTHS.values() if t.scenario == scenario and render in (None, t.render.value)
    )


class ScriptedLLM(FakeLLMClient):
    """Answers extraction with the ground truth of the file being processed."""

    def __init__(self) -> None:
        self.current: GroundTruth | None = None
        self.investigation: list[Outcome] = []
        self.fail_extraction_with: Exception | None = None
        super().__init__(self._respond)

    def _respond(self, request: CompletionRequest) -> Outcome:
        if request.tools is not None or "investigator" in str(request.messages[0]["content"]):
            if self.investigation:
                return self.investigation.pop(0)
            return json.dumps({"summary": "Resumen.", "recommendation": "Revisar."})
        if self.fail_extraction_with is not None:
            return self.fail_extraction_with
        assert self.current is not None
        return self.current.extraction.model_dump_json()


def build_test_container(
    session_factory: sessionmaker[Session], llm: ScriptedLLM, settings: Settings | None = None
) -> Container:
    with session_factory() as session, session.begin():
        seed_catalog(session, load_catalog(DATA / "catalog.json"))
    deps = AgentDeps(
        session_factory=session_factory,
        llm=llm,
        extractor=InvoiceExtractor(llm, text_model="text-m", vision_model="vision-m"),
        reasoning_model="text-m",
        today=lambda: date(2026, 10, 11),
    )
    return Container(
        settings=settings or Settings(environment=Environment.TEST),
        session_factory=session_factory,
        deps=deps,
        processor=InvoiceProcessor(deps, InMemorySaver()),
    )
