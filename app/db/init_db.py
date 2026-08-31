"""Schema creation.

Phase 0 creates the schema with ``create_all()`` and no migration tool. Alembic is
deliberately absent: the schema is young, and a hackathon does not benefit from
versioned migrations (Requirement 2.11).
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect

from app.core.logging import get_logger
from app.db.base import Base
from app.db.session import get_engine

# Importing the models package registers all seven tables on Base.metadata.
import app.models  # noqa: F401

logger = get_logger("db")


def create_all(engine: Engine | None = None) -> Engine:
    """Create every table that does not yet exist."""
    target = engine or get_engine()
    Base.metadata.create_all(bind=target)
    logger.info("Database schema ready at %s", target.url)
    return target


def drop_all(engine: Engine | None = None) -> Engine:
    """Drop every table. Used by tests and by a deliberate local reset."""
    target = engine or get_engine()
    Base.metadata.drop_all(bind=target)
    return target


def table_names(engine: Engine | None = None) -> list[str]:
    """Return the tables currently present in the database."""
    return sorted(inspect(engine or get_engine()).get_table_names())
