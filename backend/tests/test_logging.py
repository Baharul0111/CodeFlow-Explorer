from __future__ import annotations

import logging

import structlog

from app.logging_setup import configure_logging, redact, redact_processor


def test_redact_replaces_keys() -> None:
    text = "key sk-ant-api03-abcdefghijklmnop-XYZ failed"
    assert "sk-ant-api03" not in redact(text)
    assert "REDACTED" in redact(text)


def test_processor_redacts_nested_values() -> None:
    event = {
        "event": "boom sk-ant-abcdefghijk",
        "ctx": {"headers": ["x-api-key: sk-ant-abcdefghijk"]},
        "exc": ValueError("sk-ant-abcdefghijk"),
    }
    out = redact_processor(logging.getLogger(), "info", event)
    flat = repr(out)
    assert "sk-ant-abcdefghijk" not in flat
    assert flat.count("REDACTED") == 3


def test_configure_logging_pipeline_redacts(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging("INFO", json_output=True)
    structlog.get_logger("t").info("test", key="sk-ant-abcdefghijklmnop")
    captured = capsys.readouterr().err
    assert "sk-ant-abcdefghijklmnop" not in captured
    assert "REDACTED" in captured
