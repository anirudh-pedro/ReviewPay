"""Migration, legacy-adoption, and database-integrity contracts.

Two databases are exercised:

- an **initialized** database built by running every migration from empty, and
- a **pre-remediation** database built by ``create_all`` of the original seven
  domain tables and then stamped, which is what an existing Phase 0 deployment
  looks like (Requirement 10.9).

Integrity assertions run against a migrated database with SQLite foreign-key
enforcement enabled, because SQLite parses foreign keys but ignores them unless
the pragma is set (Requirement 10.6, 10.7).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.base import Base
from app.db.integrity import (
    AUDIT_IMMUTABLE_TRIGGER,
    AUDIT_SEQUENCE_UNIQUE_INDEX,
    OPEN_RECOVERY_CASE_INDEX,
    PAYMENT_ATTEMPT_UNIQUE_INDEX,
)
from app.db.session import enforce_sqlite_integrity
from app.models import LEGACY_DOMAIN_MODELS
import app.models  # noqa: F401 - register metadata for legacy bootstrap simulation

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
LEGACY_TABLES = {
    "customers", "payments", "payment_attempts", "recovery_cases",
    "recovery_actions", "recovery_outcomes", "audit_events",
}
GATEWAY_TABLES = {"gateway_payments", "gateway_webhook_events"}
HEAD_REVISION = "20260829_04"

NOW = datetime(2026, 1, 1, 13, 0, 0)


def _config(database) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def _engine(database, *, enforce: bool = True):
    engine = create_engine(f"sqlite:///{database}", future=True)
    return enforce_sqlite_integrity(engine) if enforce else engine


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


# ---------------------------------------------------------------------------
# Forward upgrade
# ---------------------------------------------------------------------------


def test_empty_sqlite_upgrades_to_head(tmp_path):
    database = tmp_path / "empty.db"
    command.upgrade(_config(database), "head")
    engine = _engine(database)
    names = set(inspect(engine).get_table_names())
    assert LEGACY_TABLES <= names
    assert {"background_jobs", "outbox_events"} <= names
    assert GATEWAY_TABLES <= names
    assert _revision(engine) == HEAD_REVISION
    engine.dispose()


def test_existing_legacy_sqlite_can_be_stamped_then_upgraded(tmp_path):
    database = tmp_path / "legacy.db"
    engine = _engine(database)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in LEGACY_DOMAIN_MODELS])
    engine.dispose()

    config = _config(database)
    command.stamp(config, "20260829_01")
    command.upgrade(config, "head")

    engine = _engine(database)
    names = set(inspect(engine).get_table_names())
    assert LEGACY_TABLES <= names
    assert {"background_jobs", "outbox_events"} <= names
    assert GATEWAY_TABLES <= names
    assert _revision(engine) == HEAD_REVISION
    engine.dispose()


def test_readiness_integrity_migration_is_reversible(tmp_path):
    """Forward-only for release, but the revision itself is not a dead end."""
    database = tmp_path / "reversible.db"
    config = _config(database)
    command.upgrade(config, "head")
    command.downgrade(config, "20260829_03")

    engine = _engine(database)
    indexes = {index["name"] for index in inspect(engine).get_indexes("recovery_cases")}
    assert OPEN_RECOVERY_CASE_INDEX not in indexes
    # The audit ordering guarantee predates this revision and must survive it.
    audit_indexes = {index["name"] for index in inspect(engine).get_indexes("audit_events")}
    assert AUDIT_SEQUENCE_UNIQUE_INDEX in audit_indexes
    assert _revision(engine) == "20260829_03"
    engine.dispose()


def test_bootstrapped_current_schema_can_be_stamped_then_upgraded(tmp_path):
    """The documented local/test bootstrap already carries the new constraints.

    ``create_all`` builds the declarative models, which now declare every guard
    this revision installs. Re-issuing them would abort the upgrade, so the
    migration installs only what is absent and installs it exactly once
    (Requirement 10.1, 10.9).
    """
    database = tmp_path / "bootstrapped.db"
    engine = _engine(database)
    Base.metadata.create_all(engine)
    engine.dispose()

    config = _config(database)
    command.stamp(config, "20260829_03")
    command.upgrade(config, "head")

    engine = _engine(database)
    inspector = inspect(engine)
    assert _revision(engine) == HEAD_REVISION

    case_indexes = [
        index["name"] for index in inspector.get_indexes("recovery_cases")
    ]
    assert case_indexes.count(OPEN_RECOVERY_CASE_INDEX) == 1
    attempt_indexes = [
        index["name"] for index in inspector.get_indexes("payment_attempts")
    ]
    assert attempt_indexes.count(PAYMENT_ATTEMPT_UNIQUE_INDEX) == 1
    action_keys = [
        key["name"] for key in inspector.get_foreign_keys("recovery_actions")
    ]
    assert action_keys.count("fk_recovery_actions_payment_id_payments") == 1
    engine.dispose()


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _seed_payment(connection, payment_id: str = "pay_pre_0001") -> str:
    """Insert the minimum customer/payment pair the case rows reference."""
    connection.execute(
        text(
            "INSERT INTO customers (customer_id, historical_payment_count, "
            "successful_payment_count, failed_payment_count, historical_success_rate, "
            "average_transaction_value, subscription_status, metadata, is_synthetic, "
            "created_at, updated_at) VALUES ('cus_pre_0001', 0, 0, 0, 0.0, 0, "
            "'NONE', '{}', 1, :now, :now)"
        ),
        {"now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO payments (payment_id, customer_id, amount, currency, "
            "payment_method, status, attempt_count, failure_reason, merchant_id, "
            "metadata, is_synthetic, created_at, updated_at) VALUES (:pid, "
            "'cus_pre_0001', 5000, 'INR', 'CARD', 'FAILED', 1, 'INSUFFICIENT_FUNDS', "
            "'mer_pre', '{}', 1, :now, :now)"
        ),
        {"pid": payment_id, "now": NOW},
    )
    return payment_id


def _pre_remediation_database(tmp_path, name: str):
    """A database at revision 03: the shape that existed before this revision."""
    database = tmp_path / name
    command.upgrade(_config(database), "20260829_03")
    return database


def test_preflight_blocks_the_upgrade_when_open_cases_are_duplicated(tmp_path):
    """Requirement 10.7: block and report instead of deleting or mutating rows."""
    database = _pre_remediation_database(tmp_path, "duplicate_open.db")

    engine = _engine(database)
    with engine.begin() as connection:
        payment_id = _seed_payment(connection)
        for suffix in ("a", "b"):
            connection.execute(
                text(
                    "INSERT INTO recovery_cases (case_id, payment_id, state, "
                    "amount_at_risk, created_at, updated_at) VALUES "
                    "(:cid, :pid, 'DETECTED', 5000, :now, :now)"
                ),
                {"cid": f"case_pre_{suffix}", "pid": payment_id, "now": NOW},
            )
    engine.dispose()

    with pytest.raises(Exception) as raised:
        command.upgrade(_config(database), "head")

    message = str(raised.value)
    assert OPEN_RECOVERY_CASE_INDEX in message
    assert payment_id in message
    # Operator-readable and secret-free: no SQL text, no connection string.
    assert "INSERT INTO" not in message
    assert str(database) not in message

    engine = _engine(database)
    # Nothing was applied and nothing was removed.
    assert _revision(engine) == "20260829_03"
    assert OPEN_RECOVERY_CASE_INDEX not in {
        index["name"] for index in inspect(engine).get_indexes("recovery_cases")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM recovery_cases")
        ).scalar_one() == 2
    engine.dispose()


def test_terminal_cases_for_one_payment_do_not_block_the_upgrade(tmp_path):
    """The guarantee is one *open* case, not one case per payment ever."""
    database = _pre_remediation_database(tmp_path, "terminal_history.db")

    engine = _engine(database)
    with engine.begin() as connection:
        payment_id = _seed_payment(connection)
        for suffix, state in (("a", "RECOVERED"), ("b", "STOPPED"), ("c", "DETECTED")):
            connection.execute(
                text(
                    "INSERT INTO recovery_cases (case_id, payment_id, state, "
                    "amount_at_risk, created_at, updated_at) VALUES "
                    "(:cid, :pid, :state, 5000, :now, :now)"
                ),
                {
                    "cid": f"case_hist_{suffix}",
                    "pid": payment_id,
                    "state": state,
                    "now": NOW,
                },
            )
    engine.dispose()

    command.upgrade(_config(database), "head")

    engine = _engine(database)
    assert _revision(engine) == HEAD_REVISION
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM recovery_cases")
        ).scalar_one() == 3
    engine.dispose()


def test_preflight_blocks_the_upgrade_for_orphaned_action_payments(tmp_path):
    """Requirement 10.6: the action-to-payment relationship must already hold."""
    database = _pre_remediation_database(tmp_path, "orphan_action.db")

    engine = _engine(database, enforce=False)
    with engine.begin() as connection:
        payment_id = _seed_payment(connection)
        connection.execute(
            text(
                "INSERT INTO recovery_cases (case_id, payment_id, state, "
                "amount_at_risk, created_at, updated_at) VALUES "
                "('case_orphan', :pid, 'DETECTED', 5000, :now, :now)"
            ),
            {"pid": payment_id, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO recovery_actions (action_id, case_id, payment_id, "
                "action_type, estimated_probability, confidence, model_version, "
                "expected_recovery_value, erv_breakdown, risk_level, "
                "decision_explanation, status, created_at) VALUES "
                "('act_orphan', 'case_orphan', 'pay_missing_0001', 'RETRY_NOW', "
                "0.5, 0.5, 'v1', 100, '{}', 'LOW', '{}', 'PROPOSED', :now)"
            ),
            {"now": NOW},
        )
    engine.dispose()

    with pytest.raises(Exception) as raised:
        command.upgrade(_config(database), "head")

    assert "fk_recovery_actions_payment_id_payments" in str(raised.value)
    assert "act_orphan" in str(raised.value)

    engine = _engine(database)
    assert _revision(engine) == "20260829_03"
    engine.dispose()


# ---------------------------------------------------------------------------
# Enforcement on the migrated schema
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated(tmp_path):
    """A head-revision database with SQLite foreign-key enforcement on."""
    database = tmp_path / "migrated.db"
    command.upgrade(_config(database), "head")
    engine = _engine(database)
    with engine.begin() as connection:
        _seed_payment(connection)
        connection.execute(
            text(
                "INSERT INTO recovery_cases (case_id, payment_id, state, "
                "amount_at_risk, created_at, updated_at) VALUES "
                "('case_mig_0001', 'pay_pre_0001', 'DETECTED', 5000, :now, :now)"
            ),
            {"now": NOW},
        )
    yield engine
    engine.dispose()


def _insert_case(connection, case_id: str, state: str) -> None:
    connection.execute(
        text(
            "INSERT INTO recovery_cases (case_id, payment_id, state, amount_at_risk, "
            "created_at, updated_at) VALUES (:cid, 'pay_pre_0001', :state, 5000, :now, :now)"
        ),
        {"cid": case_id, "state": state, "now": NOW},
    )


def test_a_second_open_case_for_one_payment_is_rejected(migrated):
    """Requirement 10.5: at most one open case per payment."""
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            _insert_case(connection, "case_mig_0002", "DIAGNOSED")

    with migrated.connect() as connection:
        # Atomic rejection: the failed write left no partial row behind.
        assert connection.execute(
            text("SELECT COUNT(*) FROM recovery_cases")
        ).scalar_one() == 1


def test_a_case_reopened_after_a_terminal_one_is_accepted(migrated):
    """Closing a case must free the payment for a later recovery attempt."""
    with migrated.begin() as connection:
        connection.execute(
            text("UPDATE recovery_cases SET state = 'RECOVERED' WHERE case_id = :cid"),
            {"cid": "case_mig_0001"},
        )
    with migrated.begin() as connection:
        _insert_case(connection, "case_mig_0003", "DETECTED")

    with migrated.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM recovery_cases")
        ).scalar_one() == 2


def _insert_attempt(connection, attempt_id: str, number: int) -> None:
    connection.execute(
        text(
            "INSERT INTO payment_attempts (attempt_id, payment_id, attempt_number, "
            "status, provider_response, source, attempted_at) VALUES "
            "(:aid, 'pay_pre_0001', :number, 'FAILED', '{}', 'checkout', :now)"
        ),
        {"aid": attempt_id, "number": number, "now": NOW},
    )


def test_duplicate_attempt_numbers_for_one_payment_are_rejected(migrated):
    """Requirement 10.5: ``(payment_id, attempt_number)`` is the attempt key."""
    with migrated.begin() as connection:
        _insert_attempt(connection, "att_mig_0001", 1)

    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            _insert_attempt(connection, "att_mig_0002", 1)

    with migrated.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM payment_attempts")
        ).scalar_one() == 1


def test_a_nonpositive_attempt_number_is_rejected(migrated):
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            _insert_attempt(connection, "att_mig_0003", 0)


def test_an_action_referencing_an_absent_payment_is_rejected(migrated):
    """Requirement 10.6: the foreign key is enforced, not just declared."""
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO recovery_actions (action_id, case_id, payment_id, "
                    "action_type, estimated_probability, confidence, model_version, "
                    "expected_recovery_value, erv_breakdown, risk_level, "
                    "decision_explanation, status, created_at) VALUES "
                    "('act_mig_bad', 'case_mig_0001', 'pay_absent_0001', 'RETRY_NOW', "
                    "0.5, 0.5, 'v1', 100, '{}', 'LOW', '{}', 'PROPOSED', :now)"
                ),
                {"now": NOW},
            )


def test_a_job_status_outside_the_lifecycle_is_rejected(migrated):
    """Requirement 12.1: the lifecycle is closed at the persistence boundary."""
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO background_jobs (job_id, job_type, case_id, "
                    "idempotency_key, status, payload, attempts, max_attempts, "
                    "available_at, created_at, updated_at) VALUES "
                    "('job_mig_bad', 'RECOVER', NULL, 'idem_bad', 'INVENTED', '{}', "
                    "0, 3, :now, :now, :now)"
                ),
                {"now": NOW},
            )


def _insert_audit_event(connection, event_id: str, sequence: int) -> None:
    connection.execute(
        text(
            "INSERT INTO audit_events (event_id, case_id, payment_id, stage, "
            "event_type, message, sequence, metadata, timestamp) VALUES "
            "(:eid, 'case_mig_0001', 'pay_pre_0001', 'DETECTION', "
            "'REVENUE_RISK_DETECTED', 'recorded', :seq, '{}', :now)"
        ),
        {"eid": event_id, "seq": sequence, "now": NOW},
    )


def test_per_case_audit_sequence_stays_unique_and_increasing(migrated):
    """Requirement 10.8: the pre-existing ordering guarantee survives this revision."""
    with migrated.begin() as connection:
        _insert_audit_event(connection, "evt_mig_0001", 0)
        _insert_audit_event(connection, "evt_mig_0002", 1)

    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            _insert_audit_event(connection, "evt_mig_0003", 1)

    with migrated.connect() as connection:
        sequences = connection.execute(
            text(
                "SELECT sequence FROM audit_events WHERE case_id = 'case_mig_0001' "
                "ORDER BY sequence"
            )
        ).scalars().all()
    assert sequences == [0, 1]


def test_recorded_audit_content_cannot_be_updated(migrated):
    """Requirement 10.8: history is append-only at the persistence boundary."""
    with migrated.begin() as connection:
        _insert_audit_event(connection, "evt_mig_0010", 0)

    for statement in (
        "UPDATE audit_events SET message = 'rewritten' WHERE event_id = 'evt_mig_0010'",
        "UPDATE audit_events SET sequence = 9 WHERE event_id = 'evt_mig_0010'",
    ):
        with pytest.raises((IntegrityError, OperationalError)):
            with migrated.begin() as connection:
                connection.execute(text(statement))

    with migrated.connect() as connection:
        row = connection.execute(
            text(
                "SELECT message, sequence FROM audit_events WHERE event_id = 'evt_mig_0010'"
            )
        ).one()
    assert row.message == "recorded"
    assert row.sequence == 0


def test_the_audit_immutability_guard_is_installed(migrated):
    with migrated.connect() as connection:
        triggers = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        ).scalars().all()
    assert AUDIT_IMMUTABLE_TRIGGER in triggers


def test_the_attempt_unique_index_is_present_on_the_migrated_schema(migrated):
    indexes = {
        index["name"] for index in inspect(migrated).get_indexes("payment_attempts")
    }
    assert PAYMENT_ATTEMPT_UNIQUE_INDEX in indexes
