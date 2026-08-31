"""Logging configuration.

Log output is intentionally readable enough to debug a live demo: one line per
workflow stage, with the workflow id as the leading correlation key
(Requirement 23.2, 23.3).

Payment instrument credentials and customer contact details are never logged
(Requirement 23.5). Components log identifiers, states, and amounts only.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "revivepay"

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once, honouring ``LOG_LEVEL``.

    Safe to call repeatedly; only the first call installs handlers.
    """
    global _configured

    if level is None:
        # Imported lazily so that logging setup does not force settings creation
        # during module import.
        from app.core.config import get_settings

        level = get_settings().log_level

    resolved = getattr(logging, str(level).upper(), logging.INFO)

    if _configured:
        logging.getLogger().setLevel(resolved)
        logging.getLogger(LOGGER_NAME).setLevel(resolved)
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(resolved)
    root.handlers = [handler]

    logging.getLogger(LOGGER_NAME).setLevel(resolved)

    # Uvicorn access logs are noisy during demos; the request-timing middleware
    # already reports method, path, status, and duration.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced application logger."""
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")
