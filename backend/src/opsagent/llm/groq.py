"""Groq client over its OpenAI-compatible HTTP API.

Plain `httpx` instead of the vendor SDK on purpose: the SDK retries on its own,
which would multiply with our retries and hide what is happening. Here every
timeout, retry and status code is explicit and logged.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from opsagent.infra.logging import get_logger
from opsagent.llm.base import CompletionRequest, LLMResponse
from opsagent.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMRateLimitedError,
    LLMServerError,
    LLMTimeoutError,
)
from opsagent.llm.pricing import estimate_cost

log = get_logger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, LLMError) and exc.retryable


def _make_wait(scale: float) -> Callable[[RetryCallState], float]:
    backoff = wait_exponential_jitter(initial=1, max=20)

    def wait(state: RetryCallState) -> float:
        """Honour Retry-After on 429s, otherwise exponential backoff with jitter."""
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, LLMRateLimitedError) and exc.retry_after_s:
            return min(exc.retry_after_s, 60.0) * scale
        return float(backoff(state)) * scale

    return wait


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    log.warning(
        "llm_retry",
        attempt=state.attempt_number,
        error=type(exc).__name__ if exc else None,
        detail=str(exc)[:200] if exc else None,
    )


class GroqClient:
    provider = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 60.0,
        max_attempts: int = 4,
        base_url: str = GROQ_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        backoff_scale: float = 1.0,  # 0 in tests: retry without sleeping
    ) -> None:
        if not api_key:
            raise LLMAuthError("GROQ_API_KEY is not set")
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )
        self._complete_with_retry = retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max_attempts),
            wait=_make_wait(backoff_scale),
            before_sleep=_log_retry,
            reraise=True,
        )(self._complete_once)

    def complete(self, request: CompletionRequest) -> LLMResponse:
        return self._complete_with_retry(request)

    def _complete_once(self, request: CompletionRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_completion_tokens": request.max_tokens,
            **request.extra,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            response = self._http.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Groq request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise LLMServerError(f"Groq connection error: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        self._raise_for_status(response)
        body = response.json()
        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        content = body["choices"][0]["message"].get("content") or ""
        log.info(
            "llm_call",
            provider=self.provider,
            model=request.model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(request.model, prompt_tokens, completion_tokens),
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        detail = response.text[:500]
        if status == 429:
            retry_after = response.headers.get("retry-after")
            raise LLMRateLimitedError(
                f"Groq rate limit: {detail}",
                retry_after_s=float(retry_after) if retry_after else None,
            )
        if status in (401, 403):
            raise LLMAuthError(f"Groq rejected the API key ({status})")
        if status >= 500:
            raise LLMServerError(f"Groq server error {status}: {detail}")
        raise LLMBadRequestError(f"Groq bad request {status}: {detail}")

    def close(self) -> None:
        self._http.close()
