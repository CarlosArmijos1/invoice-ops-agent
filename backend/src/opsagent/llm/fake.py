"""Scripted LLM for unit tests: no network, fully deterministic."""

from collections.abc import Callable, Iterable
from decimal import Decimal

from opsagent.llm.base import CompletionRequest, LLMResponse

Responder = Callable[[CompletionRequest], str | Exception]


class FakeLLMClient:
    provider = "fake"

    def __init__(self, responses: Iterable[str | Exception] | Responder) -> None:
        self._responder: Responder | None = responses if callable(responses) else None
        self._queue: list[str | Exception] = [] if callable(responses) else list(responses)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self._responder(request) if self._responder else self._queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(
            content=outcome,
            model=request.model,
            provider=self.provider,
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=5,
            cost_usd=Decimal("0.000100"),
        )
