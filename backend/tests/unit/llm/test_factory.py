from pathlib import Path

import pytest
from pydantic import SecretStr

from opsagent.llm.cassette import CassetteLLMClient, CassetteMode
from opsagent.llm.errors import LLMAuthError
from opsagent.llm.factory import build_llm_client
from opsagent.llm.groq import GroqClient
from opsagent.settings import LLMMode, Settings


def _settings(mode: LLMMode, key: str | None, tmp_path: Path) -> Settings:
    return Settings(
        llm_mode=mode, groq_api_key=SecretStr(key) if key else None, cassette_dir=tmp_path
    )


def test_live_without_key_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(LLMAuthError):
        build_llm_client(_settings(LLMMode.LIVE, None, tmp_path))


def test_live_with_key_is_the_plain_groq_client(tmp_path: Path) -> None:
    assert isinstance(build_llm_client(_settings(LLMMode.LIVE, "k", tmp_path)), GroqClient)


@pytest.mark.parametrize("key", [None, "k"])
def test_hybrid_starts_with_or_without_key(key: str | None, tmp_path: Path) -> None:
    client = build_llm_client(_settings(LLMMode.HYBRID, key, tmp_path))
    assert isinstance(client, CassetteLLMClient)
    assert client.mode is CassetteMode.HYBRID
    assert (client.inner is not None) is (key is not None)


def test_replay_never_needs_a_key(tmp_path: Path) -> None:
    client = build_llm_client(_settings(LLMMode.REPLAY, None, tmp_path))
    assert isinstance(client, CassetteLLMClient)
    assert client.mode is CassetteMode.REPLAY
