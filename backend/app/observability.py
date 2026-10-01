from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one structured JSON object per log line.

    Application logs intentionally contain operational metadata only. Request
    paths are logged without query strings, and authentication/payment secrets
    are never included in log fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status_code", "duration_ms", "environment"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": "".join(traceback.format_exception(*record.exc_info)).strip(),
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _level_from_environment() -> int:
    value = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, value, None)
    if not isinstance(level, int):
        raise ValueError("LOG_LEVEL must be a valid Python logging level")
    return level


def configure_logging() -> None:
    """Configure WEWE application logs for container-friendly structured output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("wewe")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(_level_from_environment())
    logger.propagate = False
