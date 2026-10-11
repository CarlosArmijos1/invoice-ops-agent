from pathlib import Path

import pytest

from opsagent.llm.base import CompletionRequest, text_message
from opsagent.llm.cassette import CassetteLLMClient, CassetteMode, request_key
from opsagent.llm.errors import CassetteMissError
from opsagent.llm.fake import FakeLLMClient


def _req(text: str = "hola") -> CompletionRequest:
    return CompletionRequest(model="m", messages=[text_message("user", text)], json_mode=True)


def test_record_then_replay_without_network(tmp_path: Path) -> None:
    inner = FakeLLMClient(['{"a": 1}'])
    recorder = CassetteLLMClient(tmp_path, CassetteMode.RECORD, inner=inner)
    recorded = recorder.complete(_req())

    replayer = CassetteLLMClient(tmp_path, CassetteMode.REPLAY)
    replayed = replayer.complete(_req())

    assert replayed.content == recorded.content
    assert replayed.cost_usd == recorded.cost_usd
    assert replayed.cached is True
    assert len(inner.requests) == 1


def test_replay_miss_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(CassetteMissError):
        CassetteLLMClient(tmp_path, CassetteMode.REPLAY).complete(_req())


def test_changing_the_prompt_changes_the_key() -> None:
    assert request_key(_req("a")) != request_key(_req("b"))
    assert request_key(_req("a")) == request_key(_req("a"))


def test_hybrid_uses_recordings_and_falls_back_to_live_without_saving(tmp_path: Path) -> None:
    CassetteLLMClient(tmp_path, CassetteMode.RECORD, inner=FakeLLMClient(['"rec"'])).complete(
        _req("known")
    )
    live = FakeLLMClient(['"live"'])
    hybrid = CassetteLLMClient(tmp_path, CassetteMode.HYBRID, inner=live)

    assert hybrid.complete(_req("known")).cached is True
    assert hybrid.complete(_req("new")).content == '"live"'
    assert len(live.requests) == 1
    assert len(list(tmp_path.iterdir())) == 1  # the live answer was not recorded


def test_hybrid_without_api_key_still_serves_recordings(tmp_path: Path) -> None:
    CassetteLLMClient(tmp_path, CassetteMode.RECORD, inner=FakeLLMClient(['"rec"'])).complete(
        _req()
    )
    offline = CassetteLLMClient(tmp_path, CassetteMode.HYBRID)
    assert offline.complete(_req()).content == '"rec"'
    with pytest.raises(CassetteMissError):
        offline.complete(_req("other"))
