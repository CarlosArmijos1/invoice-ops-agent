"""Everything the graph nodes need, injected once (and replaced by fakes in tests)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session, sessionmaker

from opsagent.domain.reconciliation import PolicyConfig
from opsagent.extraction.extractor import InvoiceExtractor
from opsagent.llm.base import LLMClient
from opsagent.llm.factory import build_llm_client
from opsagent.settings import Settings


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass
class AgentDeps:
    session_factory: sessionmaker[Session]
    llm: LLMClient
    extractor: InvoiceExtractor
    reasoning_model: str
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    reasoning_extra: dict[str, object] = field(default_factory=dict)
    investigate: bool = True
    max_tool_rounds: int = 4
    today: Callable[[], date] = _today


def build_deps(settings: Settings, session_factory: sessionmaker[Session]) -> AgentDeps:
    llm = build_llm_client(settings)
    reasoning_extra: dict[str, object] = {"reasoning_effort": settings.reasoning_effort}
    return AgentDeps(
        session_factory=session_factory,
        llm=llm,
        extractor=InvoiceExtractor(
            llm,
            text_model=settings.reasoning_model,
            vision_model=settings.vision_model,
            max_attempts=settings.extraction_max_attempts,
            own_tax_id=settings.own_tax_id,
            text_model_extra=reasoning_extra,
        ),
        reasoning_model=settings.reasoning_model,
        reasoning_extra=reasoning_extra,
        policy=PolicyConfig(
            amount_tolerance_abs=settings.amount_tolerance_abs,
            amount_tolerance_pct=settings.amount_tolerance_pct,
            auto_approval_limit=settings.auto_approval_limit,
            min_quality_score=settings.min_quality_score,
        ),
        investigate=settings.investigate,
    )
