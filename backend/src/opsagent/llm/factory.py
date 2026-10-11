"""Build the configured LLM client (live, recording or replaying)."""

from opsagent.llm.base import LLMClient
from opsagent.llm.cassette import CassetteLLMClient, CassetteMode
from opsagent.llm.groq import GroqClient
from opsagent.settings import LLMMode, Settings


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mode is LLMMode.REPLAY:
        return CassetteLLMClient(settings.cassette_dir, CassetteMode.REPLAY)

    key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else ""
    groq = GroqClient(key, timeout_s=settings.llm_timeout_s, max_attempts=settings.llm_max_attempts)
    if settings.llm_mode is LLMMode.RECORD:
        return CassetteLLMClient(settings.cassette_dir, CassetteMode.RECORD, inner=groq)
    return groq
