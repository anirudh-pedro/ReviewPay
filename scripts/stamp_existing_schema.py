"""Safely mark a pre-Alembic RevivePay database at the migration head.

Use only for a database created by the former create_all() bootstrap. The command
refuses to stamp when the seven legacy tables are absent, avoiding a false schema
history on unrelated or incomplete databases.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.db.session import get_engine

LEGACY_TABLES = frozenset(
    {
        "customers", "payments", "payment_attempts", "recovery_cases",
        "recovery_actions", "recovery_outcomes", "audit_events",
    }
)


def main() -> None:
    tables = frozenset(inspect(get_engine()).get_table_names())
    missing = LEGACY_TABLES - tables
    if missing:
        raise SystemExit(
            "Refusing to stamp an incomplete schema; missing: " + ", ".join(sorted(missing))
        )
    command.stamp(Config("alembic.ini"), "head")


if __name__ == "__main__":
    main()
