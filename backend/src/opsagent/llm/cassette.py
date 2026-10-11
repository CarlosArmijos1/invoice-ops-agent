"""Record/replay wrapper ("cassettes") for deterministic, free, offline evals and CI.

- record: call the real provider and save each response under a hash of the request.
- replay: never touch the network; a request with no recording raises CassetteMissError.

The key covers model, messages (including image bytes), JSON mode and
temperature, so editing a prompt invalidates exactly the affected recordings.
"""

import hashlib
import json
from dataclasses import asdict, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from opsagent.llm.base import CompletionRequest, LLMClient, LLMResponse, ToolCall
from opsagent.llm.errors import CassetteMissError


class CassetteMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"


def request_key(request: CompletionRequest) -> str:
    canonical = json.dumps(
        {
            "model": request.model,
            "messages": request.messages,
            "json_mode": request.json_mode,
            "temperature": request.temperature,
            "extra": request.extra,
            "tools": request.tools,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class CassetteLLMClient:
    def __init__(self, directory: Path, mode: CassetteMode, inner: LLMClient | None = None):
        if mode is CassetteMode.RECORD and inner is None:
            raise ValueError("record mode needs a real client to record from")
        self.directory = directory
        self.mode = mode
        self.inner = inner
        self.provider = inner.provider if inner else "cassette"

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def complete(self, request: CompletionRequest) -> LLMResponse:
        path = self._path(request_key(request))
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["cost_usd"] = Decimal(data["cost_usd"])
            data["tool_calls"] = tuple(ToolCall(**c) for c in data.get("tool_calls", []))
            return replace(LLMResponse(**data), cached=True)
        if self.mode is CassetteMode.REPLAY or self.inner is None:
            raise CassetteMissError(
                f"No recording for request {path.stem} (model={request.model}). "
                "Re-record with LLM_MODE=record."
            )

        response = self.inner.complete(request)
        self.directory.mkdir(parents=True, exist_ok=True)
        record = asdict(response) | {"cost_usd": str(response.cost_usd)}
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return response
