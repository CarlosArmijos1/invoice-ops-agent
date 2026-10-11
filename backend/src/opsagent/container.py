"""Composition root: builds the object graph once for the API, worker, CLI and MCP server."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.orm import Session, sessionmaker

from opsagent.agent.deps import AgentDeps, build_deps
from opsagent.infra.db.session import get_engine, get_sessionmaker
from opsagent.infra.logging import configure_logging
from opsagent.services.processing import InvoiceProcessor
from opsagent.settings import Settings, get_settings


@dataclass
class Container:
    settings: Settings
    session_factory: sessionmaker[Session]
    deps: AgentDeps
    processor: InvoiceProcessor
    _closeables: list[Any] = field(default_factory=list)

    def close(self) -> None:
        for resource in self._closeables:
            resource.close()


def build_container(settings: Settings | None = None, *, checkpoints: bool = True) -> Container:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    session_factory = get_sessionmaker(get_engine(settings.database_url))
    deps = build_deps(settings, session_factory)

    closeables: list[Any] = []
    checkpointer: BaseCheckpointSaver[str] | None = None
    if checkpoints:
        from opsagent.infra.checkpoint import build_checkpointer

        checkpointer, pool = build_checkpointer(settings.database_url)
        closeables.append(pool)

    processor = InvoiceProcessor(
        deps,
        checkpointer,
        max_attempts=settings.max_processing_attempts,
        claim_timeout=timedelta(minutes=settings.claim_timeout_minutes),
    )
    return Container(settings, session_factory, deps, processor, closeables)
