import json
import logging

import pytest

from app.observability import JsonFormatter, _level_from_environment


def test_json_formatter_contains_safe_request_metadata() -> None:
    record = logging.LogRecord(
        name="wewe.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-123"
    record.method = "GET"
    record.path = "/health/ready"
    record.status_code = 200
    record.duration_ms = 12.34

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["request_id"] == "request-123"
    assert payload["path"] == "/health/ready"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.34
    assert "Authorization" not in payload
    assert "password" not in json.dumps(payload).lower()


def test_log_level_defaults_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert _level_from_environment() == logging.INFO


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        _level_from_environment()
