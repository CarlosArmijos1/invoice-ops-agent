import json

import httpx
import pytest

from opsagent.llm.base import CompletionRequest, text_message
from opsagent.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitedError,
    LLMServerError,
    LLMTimeoutError,
)
from opsagent.llm.groq import GroqClient

OK_BODY = {
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
}


def _client(handler: httpx.MockTransport, attempts: int = 4) -> GroqClient:
    return GroqClient("test-key", transport=handler, max_attempts=attempts, backoff_scale=0)


def _request(**extra: object) -> CompletionRequest:
    return CompletionRequest(
        model="openai/gpt-oss-120b",
        messages=[text_message("user", "hola")],
        json_mode=True,
        extra=dict(extra),
    )


def test_successful_call_reports_usage_cost_and_sends_json_mode() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=OK_BODY)

    response = _client(httpx.MockTransport(handler)).complete(_request(reasoning_effort="low"))

    assert response.content == '{"ok": true}'
    assert str(response.cost_usd) == "0.750000"  # 0.15 + 0.60 per million tokens
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_are_retried_until_success(status: int) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(status, headers={"retry-after": "0"}, text="busy")
        return httpx.Response(200, json=OK_BODY)

    assert _client(httpx.MockTransport(handler)).complete(_request()).content
    assert calls["n"] == 3


def test_retries_are_bounded() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    with pytest.raises(LLMRateLimitedError):
        _client(httpx.MockTransport(handler), attempts=3).complete(_request())
    assert calls["n"] == 3


def test_bad_request_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="invalid model")

    with pytest.raises(LLMBadRequestError):
        _client(httpx.MockTransport(handler)).complete(_request())
    assert calls["n"] == 1


def test_auth_error_is_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMAuthError):
        _client(httpx.MockTransport(handler)).complete(_request())


def test_timeouts_and_dropped_connections_become_retryable_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def dropped(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("reset", request=request)

    with pytest.raises(LLMTimeoutError):
        _client(httpx.MockTransport(timeout), attempts=2).complete(_request())
    with pytest.raises(LLMServerError):
        _client(httpx.MockTransport(dropped), attempts=2).complete(_request())


def test_missing_api_key_fails_fast() -> None:
    with pytest.raises(LLMAuthError):
        GroqClient("")


def test_tool_calls_are_sent_and_parsed() -> None:
    sent: list[dict[str, object]] = []
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_purchase_order", "arguments": '{"a": 1}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    tools = [{"type": "function", "function": {"name": "get_purchase_order", "parameters": {}}}]
    request = CompletionRequest(model="m", messages=[text_message("user", "x")], tools=tools)
    response = _client(httpx.MockTransport(handler)).complete(request)

    assert sent[0]["tools"] == tools
    assert sent[0]["tool_choice"] == "auto"
    assert response.content == ""
    assert response.tool_calls[0].name == "get_purchase_order"
    assert response.tool_calls[0].arguments == '{"a": 1}'
