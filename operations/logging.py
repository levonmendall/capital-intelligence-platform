"""Structured JSON logging with safe contextual fields."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """Emit one machine-readable event per log line."""

    _STANDARD = set(logging.LogRecord(None, 0, "", 0, "", (), None).__dict__)

    def __init__(self, *, service: str, environment: str, release: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.release = release

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "release": self.release,
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in self._STANDARD or key.startswith("_"):
                continue
            if key in {"password", "token", "authorization", "secret"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging(settings: Any) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if bool(getattr(settings, "json_logs", True)):
        handler.setFormatter(
            JsonFormatter(
                service=str(getattr(settings, "service_name", "capital-intelligence")),
                environment=str(getattr(settings, "environment", "development")),
                release=str(getattr(settings, "release", "development")),
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(str(getattr(settings, "log_level", "INFO")))


__all__ = ["JsonFormatter", "configure_logging", "get_request_id", "set_request_id"]
