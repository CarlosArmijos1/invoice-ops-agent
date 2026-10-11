"""Provider-agnostic LLM interface.

The rest of the system only knows `LLMClient.complete()`. Swapping Groq for
another OpenAI-compatible provider (or a local model) means writing one more
small class, not touching the agent. That already paid off once: the Llama 4
models originally planned were retired by Groq during development.
"""

import base64
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

# OpenAI-style chat messages. Content is either text or a list of parts
# (`{"type": "text", ...}` / `{"type": "image_url", ...}`).
Message = dict[str, Any]


def text_message(role: Literal["system", "user", "assistant"], text: str) -> Message:
    return {"role": role, "content": text}


def image_part(png_bytes: bytes, media_type: str = "image/png") -> dict[str, Any]:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, validated by the tool's Pydantic model

    def as_message_part(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


def assistant_tool_calls_message(content: str, calls: tuple[ToolCall, ...]) -> Message:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [c.as_message_part() for c in calls],
    }


def tool_result_message(call: ToolCall, content: str) -> Message:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    messages: list[Message]
    json_mode: bool = False
    temperature: float = 0.0
    max_tokens: int = 2048
    # Provider-specific knobs, e.g. {"reasoning_effort": "low"} for gpt-oss.
    extra: dict[str, Any] = field(default_factory=dict)
    # OpenAI-style function definitions; the model may answer with tool calls.
    tools: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost_usd: Decimal
    tool_calls: tuple[ToolCall, ...] = ()
    cached: bool = False  # served from a cassette instead of the network


class LLMClient(Protocol):
    provider: str

    def complete(self, request: CompletionRequest) -> LLMResponse: ...
