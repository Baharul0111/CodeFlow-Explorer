"""Structured logging with API-key redaction.

Every log record passes through :func:`redact_processor`, which scrubs anything that looks like an
Anthropic API key from every string value, however deeply nested. Error messages shown to users go
through :func:`redact` as well.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

API_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
REDACTED = "sk-ant-***REDACTED***"


def redact(text: str) -> str:
    """Replace any API key inside ``text`` with a placeholder."""
    return API_KEY_RE.sub(REDACTED, text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    if isinstance(value, BaseException):
        return redact(str(value))
    return value


def redact_processor(
    _logger: logging.Logger, _method: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    return {k: _redact_value(v) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared, processors=[redact_processor, renderer]
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
