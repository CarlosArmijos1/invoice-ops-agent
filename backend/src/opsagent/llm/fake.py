"""Scripted LLM for unit tests: no network, fully deterministic."""

from collections.abc import Callable, Iterable
from decimal import Decimal

from opsagent.llm.base import CompletionRequest, LLMResponse, ToolCall

# A scripted outcome: final text, an exception to raise, or tool calls to request.
Outcome = str | Exception | tuple[ToolCall, ...]
Responder = Callable[[CompletionRequest], Outcome]


class FakeLLMClient:
    provider = "fake"

    def __init__(self, responses: Iterable[Outcome] | Responder) -> None:
        self._responder: Responder | None = responses if callable(responses) else None
        self._queue: list[Outcome] = [] if callable(responses) else list(responses)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self._responder(request) if self._responder else self._queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        calls = outcome if isinstance(outcome, tuple) else ()
        return LLMResponse(
            content=outcome if isinstance(outcome, str) else "",
            model=request.model,
            provider=self.provider,
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=5,
            cost_usd=Decimal("0.000100"),
            tool_calls=calls,
        )
