"""Development schema bootstrap.

``create_all()`` and ``drop_all()`` are a documented convenience for the ``local``,
``demo``, and ``test`` profiles: they let a developer, a demo reseed, or the test
suite build a throwaway database in one step. They are **not** a deployment
mechanism.

Alembic is the only supported schema path for the ``staging`` and ``production``
profiles, so both entry points here refuse to run under those profiles rather
than creating or dropping tables underneath a live schema history
(Requirement 10.2).
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect

from app.core.config import Settings, get_settings
from app.core.errors import RevivePayError
from app.core.logging import get_logger
from app.db.base import Base
from app.db.session import get_engine

# Importing the models package registers all seven tables on Base.metadata.
import app.models  # noqa: F401

logger = get_logger("db")


class SchemaBootstrapForbidden(RevivePayError):
    """A schema-creating or destructive bootstrap was attempted in a protected profile."""

    code = "SCHEMA_BOOTSTRAP_FORBIDDEN"
    http_status = 403

    def __init__(self, operation: str, profile: str) -> None:
        super().__init__(
            f"Schema bootstrap operation '{operation}' is not permitted in the '{profile}' profile. "
            "Apply an ordered Alembic migration instead."
        )
        self.operation = operation
        self.profile = profile


def _require_bootstrap_profile(operation: str, settings: Settings | None) -> Settings:
    resolved = settings or get_settings()
    if not resolved.profile_policy.allows_schema_bootstrap:
        raise SchemaBootstrapForbidden(operation, resolved.environment_profile)
    return resolved


def create_all(engine: Engine | None = None, *, settings: Settings | None = None) -> Engine:
    """Create every table that does not yet exist (development profiles only)."""
    _require_bootstrap_profile("create_all", settings)
    target = engine or get_engine()
    Base.metadata.create_all(bind=target)
    # Log the dialect, not the URL: a connection string can carry a credential.
    logger.info("Database schema ready | dialect=%s | tables=%s", target.dialect.name, len(Base.metadata.tables))
    return target


def drop_all(engine: Engine | None = None, *, settings: Settings | None = None) -> Engine:
    """Drop every table. Used by tests and by a deliberate local reset."""
    _require_bootstrap_profile("drop_all", settings)
    target = engine or get_engine()
    Base.metadata.drop_all(bind=target)
    return target


def table_names(engine: Engine | None = None) -> list[str]:
    """Return the tables currently present in the database."""
    return sorted(inspect(engine or get_engine()).get_table_names())
