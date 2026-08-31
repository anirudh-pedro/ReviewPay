"""Database engine and session management.

The engine is built from ``DATABASE_URL`` alone, so swapping SQLite for
PostgreSQL is a configuration change with no code change (Requirement 27.10).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _engine_kwargs(database_url: str, echo: bool) -> dict:
    kwargs: dict = {"echo": echo, "future": True}
    if database_url.startswith("sqlite"):
        # check_same_thread=False lets the TestClient and the dev server share a
        # connection across threads. Sensible for a single-process Phase 0.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    return kwargs


@lru_cache
def get_engine() -> Engine:
    """Return the cached engine built from settings."""
    settings = get_settings()
    return create_engine(settings.database_url, **_engine_kwargs(settings.database_url, settings.db_echo))


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the cached session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def reset_engine_cache() -> None:
    """Dispose the engine and clear caches. Used by tests between databases."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope for scripts and services."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
