"""Migration and legacy-schema adoption contracts for Phase 4."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.base import Base
from app.models import LEGACY_DOMAIN_MODELS
import app.models  # noqa: F401 - register metadata for legacy bootstrap simulation

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
LEGACY_TABLES = {
    "customers", "payments", "payment_attempts", "recovery_cases",
    "recovery_actions", "recovery_outcomes", "audit_events",
}


def _config(database) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_empty_sqlite_upgrades_to_head(tmp_path):
    database = tmp_path / "empty.db"
    command.upgrade(_config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    assert LEGACY_TABLES <= set(inspect(engine).get_table_names())
    assert {"background_jobs", "outbox_events"} <= set(inspect(engine).get_table_names())
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260829_02"
    engine.dispose()


def test_existing_legacy_sqlite_can_be_stamped_then_upgraded(tmp_path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine, tables=[model.__table__ for model in LEGACY_DOMAIN_MODELS])
    engine.dispose()

    config = _config(database)
    command.stamp(config, "20260829_01")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    assert LEGACY_TABLES <= set(inspect(engine).get_table_names())
    assert {"background_jobs", "outbox_events"} <= set(inspect(engine).get_table_names())
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260829_02"
    engine.dispose()
