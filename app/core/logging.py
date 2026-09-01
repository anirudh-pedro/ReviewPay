"""JSON application logging with correlation context and secret redaction."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import json
import logging
import re
import sys
from typing import Iterator

LOGGER_NAME = "revivepay"
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_workflow_id: ContextVar[str] = ContextVar("workflow_id", default="-")
_job_id: ContextVar[str] = ContextVar("job_id", default="-")
_configured = False
_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|authorization|password|secret|token|database_url)\s*[:=]\s*[^\s,;]+")
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/@\s:]+(?::[^/@\s]+)?@")


def redact(value: object) -> str:
    """Remove credential-shaped content before it can reach an application log."""
    text = str(value)
    text = _URL_CREDENTIALS.sub("[REDACTED]@", text)
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": _request_id.get(),
            "workflow_id": _workflow_id.get(),
            "job_id": _job_id.get(),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str | None = None) -> None:
    global _configured
    if level is None:
        from app.core.config import get_settings
        level = get_settings().log_level
    resolved = getattr(logging, str(level).upper(), logging.INFO)
    if _configured:
        logging.getLogger().setLevel(resolved)
        logging.getLogger(LOGGER_NAME).setLevel(resolved)
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(resolved)
    root.handlers = [handler]
    logging.getLogger(LOGGER_NAME).setLevel(resolved)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


@contextmanager
def log_context(*, request_id: str | None = None, workflow_id: str | None = None, job_id: str | None = None) -> Iterator[None]:
    tokens: list[tuple[ContextVar[str], Token[str]]] = []
    for variable, value in ((_request_id, request_id), (_workflow_id, workflow_id), (_job_id, job_id)):
        if value is not None:
            tokens.append((variable, variable.set(value)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
