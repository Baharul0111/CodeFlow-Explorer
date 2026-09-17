"""LLM errors with plain-English messages for non-programmers.

Every Anthropic SDK exception is mapped to one of these so the UI never shows raw API text, and
:func:`app.logging_setup.redact` is applied so a key can never leak through a message.
"""

from __future__ import annotations

from app.api.errors import AppError

INVALID_KEY = "This key is not valid. Check it and paste it again."
NO_CREDITS = "Your account has no credits. Add credits in the Anthropic console and try again."
MODEL_UNAVAILABLE = "This model isn't available for your key. Pick a different model."
RATE_LIMITED = "Too many requests, retrying…"
OVERLOADED = "Claude is busy right now. Retrying…"
CONNECTION = "Could not reach Claude. Check your internet connection and try again."
REFUSED = "Claude declined to answer for this part of the code. This step was skipped."
TOO_LARGE = "This part of the code is too big to send in one go."
BAD_OUTPUT = "Claude's answer did not match the required format after retries."
SPEND_LIMIT = "Your Anthropic spending limit was reached. Raise it in the console and try again."


class LlmError(AppError):
    """An error from the Claude layer. ``message`` is safe to show to the user."""

    status_code = 502
    code = "llm_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)
        self.retryable = retryable
        self.retry_after = retry_after


class InvalidKeyError(LlmError):
    status_code = 401
    code = "invalid_key"

    def __init__(self, message: str = INVALID_KEY) -> None:
        super().__init__(message)


class NoCreditsError(LlmError):
    status_code = 402
    code = "no_credits"

    def __init__(self, message: str = NO_CREDITS) -> None:
        super().__init__(message)


class ModelUnavailableError(LlmError):
    status_code = 404
    code = "model_unavailable"

    def __init__(self, message: str = MODEL_UNAVAILABLE) -> None:
        super().__init__(message)


class RateLimitedError(LlmError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str = RATE_LIMITED, retry_after: float | None = None) -> None:
        super().__init__(message, retryable=True, retry_after=retry_after)


class OverloadedError(LlmError):
    status_code = 503
    code = "overloaded"

    def __init__(self, message: str = OVERLOADED, retry_after: float | None = None) -> None:
        super().__init__(message, retryable=True, retry_after=retry_after)


class ConnectionFailedError(LlmError):
    status_code = 503
    code = "connection_failed"

    def __init__(self, message: str = CONNECTION) -> None:
        super().__init__(message, retryable=True)


class RefusalError(LlmError):
    status_code = 422
    code = "refused"

    def __init__(self, message: str = REFUSED) -> None:
        super().__init__(message)


class BadOutputError(LlmError):
    status_code = 502
    code = "bad_output"

    def __init__(self, message: str = BAD_OUTPUT) -> None:
        super().__init__(message)


class CostLimitError(LlmError):
    status_code = 409
    code = "cost_limit"
