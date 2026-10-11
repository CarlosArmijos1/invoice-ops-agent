"""LLM error taxonomy. The split that matters is *retryable* vs *not retryable*."""


class LLMError(Exception):
    retryable: bool = False


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRateLimitedError(LLMError):
    retryable = True

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMServerError(LLMError):
    """5xx or a dropped connection: the provider's problem, worth retrying."""

    retryable = True


class LLMBadRequestError(LLMError):
    """4xx (other than 429): our request is wrong; retrying the same thing will not help."""


class LLMAuthError(LLMError):
    """Missing or invalid API key."""


class CassetteMissError(LLMError):
    """Replay mode found no recorded response for this exact request."""
