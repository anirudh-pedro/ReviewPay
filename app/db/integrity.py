"""Database Integrity Constraint definitions shared by the models and Alembic.

One module owns every constraint predicate so the declarative models, the
``create_all`` bootstrap used by local/test profiles, and the versioned Alembic
migrations cannot drift apart (Requirement 10.1, 10.5-10.8).

Three kinds of guarantee live here:

- **Named constraint predicates** (``*_CHECK`` / ``*_PREDICATE``) written as
  portable SQL text so the identical expression is emitted on SQLite and on
  PostgreSQL. No dialect-specific boolean literal is used: ``recovered`` is
  evaluated for truth directly rather than compared to ``1`` or ``true``.
- **The open-case uniqueness predicate**, a partial-index filter. One payment may
  accumulate many *terminal* recovery cases over its life, so a plain unique key
  on ``payment_id`` would be wrong. The guarantee that matters is that a payment
  never has two *open* cases at once, which is what ``RiskDetector`` already
  assumes when it reuses an open case instead of opening a second one. SQLite
  (3.8.0+) and PostgreSQL both support partial indexes, so this is expressible
  without dialect-specific code.
- **Audit immutability DDL**, a ``BEFORE UPDATE`` trigger on ``audit_events``.
  ``AuditService`` exposes no update path, but Requirement 10.8 asks the database
  itself to preserve audit content and per-case sequence order. The trigger
  rejects the update at the persistence boundary rather than trusting callers.
  Deletion is deliberately *not* blocked: the documented local/test reset path and
  the ``RecoveryCase`` delete-orphan cascade both remove whole cases, and a
  delete guard would break them without adding a production guarantee (staging
  and production never expose a reset).
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.schema import Table

from app.core.enums import CaseState

# ---------------------------------------------------------------------------
# Recovery case open-state uniqueness
# ---------------------------------------------------------------------------

#: Case states from which no transition is permitted, sorted for stable DDL.
TERMINAL_CASE_STATES: tuple[str, ...] = tuple(
    sorted(state.value for state in CaseState.terminal())
)

#: Partial-index filter selecting the non-terminal (open) recovery cases.
OPEN_RECOVERY_CASE_PREDICATE = "state NOT IN ({values})".format(
    values=", ".join(f"'{state}'" for state in TERMINAL_CASE_STATES)
)

#: Unique index name guaranteeing at most one open case per payment.
OPEN_RECOVERY_CASE_INDEX = "uq_recovery_cases_open_payment"

# ---------------------------------------------------------------------------
# Payment attempt identity and bounds
# ---------------------------------------------------------------------------

#: Unique index name for the authoritative attempt key.
PAYMENT_ATTEMPT_UNIQUE_INDEX = "uq_payment_attempts_payment_attempt_number"

PAYMENT_ATTEMPT_NUMBER_CHECK = "ck_payment_attempts_attempt_number_positive"
PAYMENT_ATTEMPT_NUMBER_PREDICATE = "attempt_number >= 1"

# ---------------------------------------------------------------------------
# Recovery outcome state consistency
# ---------------------------------------------------------------------------

RECOVERY_OUTCOME_AMOUNT_CHECK = "ck_recovery_outcomes_recovered_amount"
#: A negative recovered amount is never valid, and an unrecovered outcome must
#: carry zero, so recovered revenue can only be summed from recovered outcomes.
RECOVERY_OUTCOME_AMOUNT_PREDICATE = (
    "recovered_amount >= 0 AND (recovered OR recovered_amount = 0)"
)

# ---------------------------------------------------------------------------
# Background job lifecycle and attempt bounds
# ---------------------------------------------------------------------------

#: The closed Background Job lifecycle (Requirement 12.1). ``CANCELLED`` is
#: included now so the constraint does not have to be rebuilt when the lifecycle
#: service starts writing it.
JOB_LIFECYCLE_STATES: tuple[str, ...] = (
    "PENDING",
    "RUNNING",
    "RETRY",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)

JOB_STATUS_CHECK = "ck_background_jobs_status"
JOB_STATUS_PREDICATE = "status IN ({values})".format(
    values=", ".join(f"'{state}'" for state in JOB_LIFECYCLE_STATES)
)

JOB_ATTEMPT_BOUNDS_CHECK = "ck_background_jobs_attempt_bounds"
JOB_ATTEMPT_BOUNDS_PREDICATE = (
    "attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts"
)

JOB_CASE_FOREIGN_KEY = "fk_background_jobs_case_id_recovery_cases"

# ---------------------------------------------------------------------------
# Outbox bounds
# ---------------------------------------------------------------------------

OUTBOX_ATTEMPTS_CHECK = "ck_outbox_events_attempts_nonnegative"
OUTBOX_ATTEMPTS_PREDICATE = "attempts >= 0"

# ---------------------------------------------------------------------------
# Recovery action relationships
# ---------------------------------------------------------------------------

ACTION_PAYMENT_FOREIGN_KEY = "fk_recovery_actions_payment_id_payments"

# ---------------------------------------------------------------------------
# Audit immutability
# ---------------------------------------------------------------------------

AUDIT_SEQUENCE_UNIQUE_INDEX = "uq_audit_events_case_sequence"
AUDIT_IMMUTABLE_TRIGGER = "trg_audit_events_immutable"
AUDIT_IMMUTABLE_FUNCTION = "revivepay_reject_audit_event_update"

#: Operator-readable, secret-free. Kept free of apostrophes because it is
#: embedded in single-quoted SQL string literals on both dialects.
AUDIT_IMMUTABLE_MESSAGE = (
    "audit_events is append-only: event content and per-case sequence "
    "cannot be updated"
)


def audit_immutability_statements(dialect: str) -> tuple[str, ...]:
    """DDL installing the append-only guard for ``audit_events``.

    Idempotent on both dialects so a bootstrapped database can be stamped and
    then migrated without the statement failing a second time.
    """
    if dialect == "sqlite":
        return (
            f"CREATE TRIGGER IF NOT EXISTS {AUDIT_IMMUTABLE_TRIGGER} "
            "BEFORE UPDATE ON audit_events "
            f"BEGIN SELECT RAISE(ABORT, '{AUDIT_IMMUTABLE_MESSAGE}'); END",
        )
    if dialect == "postgresql":
        return (
            f"CREATE OR REPLACE FUNCTION {AUDIT_IMMUTABLE_FUNCTION}() "
            "RETURNS trigger AS $$ BEGIN "
            f"RAISE EXCEPTION '{AUDIT_IMMUTABLE_MESSAGE}'; "
            "END; $$ LANGUAGE plpgsql",
            f"DROP TRIGGER IF EXISTS {AUDIT_IMMUTABLE_TRIGGER} ON audit_events",
            f"CREATE TRIGGER {AUDIT_IMMUTABLE_TRIGGER} BEFORE UPDATE ON audit_events "
            f"FOR EACH ROW EXECUTE PROCEDURE {AUDIT_IMMUTABLE_FUNCTION}()",
        )
    # Any other dialect keeps the application-level append-only guarantee only.
    return ()


def drop_audit_immutability_statements(dialect: str) -> tuple[str, ...]:
    """DDL removing the append-only guard, used by the migration downgrade."""
    if dialect == "sqlite":
        return (f"DROP TRIGGER IF EXISTS {AUDIT_IMMUTABLE_TRIGGER}",)
    if dialect == "postgresql":
        return (
            f"DROP TRIGGER IF EXISTS {AUDIT_IMMUTABLE_TRIGGER} ON audit_events",
            f"DROP FUNCTION IF EXISTS {AUDIT_IMMUTABLE_FUNCTION}()",
        )
    return ()


def install_audit_immutability(table: Table) -> None:
    """Emit the append-only guard whenever ``audit_events`` is created.

    Keeps the ``create_all`` bootstrap used by local and test profiles equivalent
    to the migrated schema. Staging and production reach the same state through
    the Alembic migration instead.
    """

    def _after_create(target: Table, connection, **_: object) -> None:
        from sqlalchemy import text as _text

        for statement in audit_immutability_statements(connection.dialect.name):
            connection.execute(_text(statement))

    event.listen(table, "after_create", _after_create)


__all__ = [
    "ACTION_PAYMENT_FOREIGN_KEY",
    "AUDIT_IMMUTABLE_FUNCTION",
    "AUDIT_IMMUTABLE_MESSAGE",
    "AUDIT_IMMUTABLE_TRIGGER",
    "AUDIT_SEQUENCE_UNIQUE_INDEX",
    "JOB_ATTEMPT_BOUNDS_CHECK",
    "JOB_ATTEMPT_BOUNDS_PREDICATE",
    "JOB_CASE_FOREIGN_KEY",
    "JOB_LIFECYCLE_STATES",
    "JOB_STATUS_CHECK",
    "JOB_STATUS_PREDICATE",
    "OPEN_RECOVERY_CASE_INDEX",
    "OPEN_RECOVERY_CASE_PREDICATE",
    "OUTBOX_ATTEMPTS_CHECK",
    "OUTBOX_ATTEMPTS_PREDICATE",
    "PAYMENT_ATTEMPT_NUMBER_CHECK",
    "PAYMENT_ATTEMPT_NUMBER_PREDICATE",
    "PAYMENT_ATTEMPT_UNIQUE_INDEX",
    "RECOVERY_OUTCOME_AMOUNT_CHECK",
    "RECOVERY_OUTCOME_AMOUNT_PREDICATE",
    "TERMINAL_CASE_STATES",
    "audit_immutability_statements",
    "drop_audit_immutability_statements",
    "install_audit_immutability",
]
