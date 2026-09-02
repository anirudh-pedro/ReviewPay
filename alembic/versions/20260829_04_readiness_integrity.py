"""Add readiness integrity constraints to the established recovery schema.

Revision ID: 20260829_04
Revises: 20260829_03

Forward-only, and deliberately in two phases.

**Phase 1 - preflight.** Every constraint this migration installs is first checked
as a read-only query against the existing rows. If any row would violate a new
constraint, the migration raises with an operator-readable, secret-free report
naming the check, the row count, and a bounded sample of the offending domain
identifiers. Nothing is deleted, mutated, or silently skipped: remediating the
data is an operator decision, not a migration side effect.

**Phase 2 - DDL.** Constraints are then installed, each one only where the schema
does not already carry it. PostgreSQL runs the whole migration inside one
transaction, so it is atomic. SQLite cannot ``ALTER TABLE ADD CONSTRAINT`` and
Alembic reports non-transactional DDL for it, so each affected table is rebuilt
through ``op.batch_alter_table`` and every validation is completed *before* the
first DDL statement runs. That ordering is what keeps the SQLite path safe without
transactional DDL.

Historical audit content is never rewritten. ``audit_events`` is the one table
this migration does not rebuild; it gains only a ``BEFORE UPDATE`` guard, and its
existing unique ``(case_id, sequence)`` index from ``20260829_02`` is left exactly
as it is rather than duplicated.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.integrity import (
    ACTION_PAYMENT_FOREIGN_KEY,
    JOB_ATTEMPT_BOUNDS_CHECK,
    JOB_ATTEMPT_BOUNDS_PREDICATE,
    JOB_CASE_FOREIGN_KEY,
    JOB_STATUS_CHECK,
    JOB_STATUS_PREDICATE,
    OPEN_RECOVERY_CASE_INDEX,
    OPEN_RECOVERY_CASE_PREDICATE,
    OUTBOX_ATTEMPTS_CHECK,
    OUTBOX_ATTEMPTS_PREDICATE,
    PAYMENT_ATTEMPT_NUMBER_CHECK,
    PAYMENT_ATTEMPT_NUMBER_PREDICATE,
    PAYMENT_ATTEMPT_UNIQUE_INDEX,
    RECOVERY_OUTCOME_AMOUNT_CHECK,
    RECOVERY_OUTCOME_AMOUNT_PREDICATE,
    audit_immutability_statements,
    drop_audit_immutability_statements,
)

revision = "20260829_04"
down_revision = "20260829_03"
branch_labels = None
depends_on = None

#: How many offending identifiers a blocked upgrade reports per check. Bounded so
#: the message stays readable on a large database.
SAMPLE_LIMIT = 5


class ReadinessIntegrityPreflightError(RuntimeError):
    """Existing rows would violate a constraint this migration installs."""


# ---------------------------------------------------------------------------
# Presence inspection
# ---------------------------------------------------------------------------
#
# Every guard below is installed only where it is absent. Two supported databases
# reach this revision already carrying some of them:
#
# - a database bootstrapped by the documented local/test ``create_all`` path,
#   which builds the current declarative models and is then stamped at an earlier
#   revision, and
# - the pre-remediation fixture Requirement 10.9 asks to be validated.
#
# Re-issuing ``CREATE UNIQUE INDEX`` or re-adding a check constraint on either of
# those would abort the upgrade even though the guarantee is already satisfied.
# Skipping a satisfied guarantee is not a weaker constraint: the post-upgrade
# schema is identical either way, and the preflight in phase 1 still validates the
# rows regardless of where the constraint came from.


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Index and unique-constraint names present on ``table``."""
    names = {index["name"] for index in inspector.get_indexes(table)}
    names |= {unique["name"] for unique in inspector.get_unique_constraints(table)}
    return {name for name in names if name}


def _check_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Check-constraint names present on ``table``.

    A dialect that cannot report check constraints yields an empty set, which
    keeps the migration installing rather than silently skipping.
    """
    try:
        constraints = inspector.get_check_constraints(table)
    except NotImplementedError:  # pragma: no cover - dialect dependent
        return set()
    return {constraint["name"] for constraint in constraints if constraint.get("name")}


def _foreign_key_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Named foreign keys present on ``table``. Unnamed keys cannot be matched."""
    return {
        key["name"] for key in inspector.get_foreign_keys(table) if key.get("name")
    }


def _preflight_checks() -> tuple[tuple[str, str, str, str], ...]:
    """Return ``(check, remedy, identifier_label, sql)`` for every guard.

    Each statement selects one column of offending domain identifiers. Domain
    identifiers are not secret; no payload, credential, or contact value is read.
    """
    return (
        (
            OPEN_RECOVERY_CASE_INDEX,
            "Close or merge the duplicate open cases so each payment has at most one.",
            "payment_id",
            f"""
            SELECT payment_id FROM recovery_cases
            WHERE {OPEN_RECOVERY_CASE_PREDICATE}
            GROUP BY payment_id HAVING COUNT(*) > 1
            """,
        ),
        (
            PAYMENT_ATTEMPT_UNIQUE_INDEX,
            "Renumber or remove the duplicate attempt rows for the listed payments.",
            "payment_id",
            """
            SELECT payment_id FROM payment_attempts
            GROUP BY payment_id, attempt_number HAVING COUNT(*) > 1
            """,
        ),
        (
            PAYMENT_ATTEMPT_NUMBER_CHECK,
            "Attempt numbers start at 1; correct the listed attempt rows.",
            "attempt_id",
            f"SELECT attempt_id FROM payment_attempts WHERE NOT ({PAYMENT_ATTEMPT_NUMBER_PREDICATE})",
        ),
        (
            ACTION_PAYMENT_FOREIGN_KEY,
            "Restore the missing payments or remove the orphaned recovery actions.",
            "action_id",
            """
            SELECT action_id FROM recovery_actions
            WHERE payment_id NOT IN (SELECT payment_id FROM payments)
            """,
        ),
        (
            RECOVERY_OUTCOME_AMOUNT_CHECK,
            "An unrecovered outcome must carry a zero recovered amount.",
            "outcome_id",
            f"SELECT outcome_id FROM recovery_outcomes WHERE NOT ({RECOVERY_OUTCOME_AMOUNT_PREDICATE})",
        ),
        (
            JOB_CASE_FOREIGN_KEY,
            "Restore the missing recovery cases or clear the job case reference.",
            "job_id",
            """
            SELECT job_id FROM background_jobs
            WHERE case_id IS NOT NULL
              AND case_id NOT IN (SELECT case_id FROM recovery_cases)
            """,
        ),
        (
            JOB_STATUS_CHECK,
            "Map the legacy job status onto the supported lifecycle before upgrading.",
            "job_id",
            f"SELECT job_id FROM background_jobs WHERE NOT ({JOB_STATUS_PREDICATE})",
        ),
        (
            JOB_ATTEMPT_BOUNDS_CHECK,
            "Correct the attempt counters so 0 <= attempts <= max_attempts and max_attempts >= 1.",
            "job_id",
            f"SELECT job_id FROM background_jobs WHERE NOT ({JOB_ATTEMPT_BOUNDS_PREDICATE})",
        ),
        (
            OUTBOX_ATTEMPTS_CHECK,
            "Correct the negative delivery attempt counters.",
            "event_id",
            f"SELECT event_id FROM outbox_events WHERE NOT ({OUTBOX_ATTEMPTS_PREDICATE})",
        ),
    )


def _run_preflight(connection: sa.Connection) -> None:
    """Block the upgrade when any existing row would violate a new constraint."""
    present = set(sa.inspect(connection).get_table_names())
    findings: list[str] = []

    for check, remedy, label, statement in _preflight_checks():
        # A pre-remediation database may predate a table; nothing to validate then.
        referenced = {
            name
            for name in (
                "recovery_cases",
                "payment_attempts",
                "recovery_actions",
                "recovery_outcomes",
                "background_jobs",
                "outbox_events",
                "payments",
            )
            if name in statement
        }
        if not referenced <= present:
            continue

        rows = connection.execute(sa.text(statement)).scalars().all()
        if not rows:
            continue

        sample = ", ".join(str(value) for value in rows[:SAMPLE_LIMIT])
        overflow = "" if len(rows) <= SAMPLE_LIMIT else f" (+{len(rows) - SAMPLE_LIMIT} more)"
        findings.append(
            f"  - {check}: {len(rows)} offending row group(s); "
            f"{label} {sample}{overflow}. {remedy}"
        )

    if findings:
        raise ReadinessIntegrityPreflightError(
            "Migration 20260829_04 was not applied: existing rows would violate the "
            "readiness integrity constraints. No schema change and no data change "
            "was made. Resolve the findings below and run the upgrade again.\n"
            + "\n".join(findings)
        )


def upgrade() -> None:
    connection = op.get_bind()
    _run_preflight(connection)

    dialect = connection.dialect.name
    inspector = sa.inspect(connection)

    # Read the whole current shape before any DDL runs, so the SQLite rebuilds
    # below cannot observe a half-migrated schema.
    attempt_checks = _check_names(inspector, "payment_attempts")
    action_keys = _foreign_key_names(inspector, "recovery_actions")
    outcome_checks = _check_names(inspector, "recovery_outcomes")
    job_checks = _check_names(inspector, "background_jobs")
    job_keys = _foreign_key_names(inspector, "background_jobs")
    outbox_checks = _check_names(inspector, "outbox_events")
    case_indexes = _index_names(inspector, "recovery_cases")

    # --- checks and foreign keys -----------------------------------------
    # ``batch_alter_table`` is a plain ``ALTER TABLE`` on PostgreSQL and a
    # copy-and-swap rebuild on SQLite. The rebuilds run before the new indexes are
    # created so no index has to survive a table swap, and a table with nothing
    # left to add is never rebuilt at all.
    if PAYMENT_ATTEMPT_NUMBER_CHECK not in attempt_checks:
        with op.batch_alter_table("payment_attempts") as batch:
            batch.create_check_constraint(
                PAYMENT_ATTEMPT_NUMBER_CHECK, PAYMENT_ATTEMPT_NUMBER_PREDICATE
            )

    if ACTION_PAYMENT_FOREIGN_KEY not in action_keys:
        with op.batch_alter_table("recovery_actions") as batch:
            batch.create_foreign_key(
                ACTION_PAYMENT_FOREIGN_KEY,
                "payments",
                ["payment_id"],
                ["payment_id"],
            )

    if RECOVERY_OUTCOME_AMOUNT_CHECK not in outcome_checks:
        with op.batch_alter_table("recovery_outcomes") as batch:
            batch.create_check_constraint(
                RECOVERY_OUTCOME_AMOUNT_CHECK, RECOVERY_OUTCOME_AMOUNT_PREDICATE
            )

    job_additions = (
        JOB_STATUS_CHECK not in job_checks
        or JOB_ATTEMPT_BOUNDS_CHECK not in job_checks
        or JOB_CASE_FOREIGN_KEY not in job_keys
    )
    if job_additions:
        with op.batch_alter_table("background_jobs") as batch:
            if JOB_STATUS_CHECK not in job_checks:
                batch.create_check_constraint(JOB_STATUS_CHECK, JOB_STATUS_PREDICATE)
            if JOB_ATTEMPT_BOUNDS_CHECK not in job_checks:
                batch.create_check_constraint(
                    JOB_ATTEMPT_BOUNDS_CHECK, JOB_ATTEMPT_BOUNDS_PREDICATE
                )
            if JOB_CASE_FOREIGN_KEY not in job_keys:
                batch.create_foreign_key(
                    JOB_CASE_FOREIGN_KEY,
                    "recovery_cases",
                    ["case_id"],
                    ["case_id"],
                )

    if OUTBOX_ATTEMPTS_CHECK not in outbox_checks:
        with op.batch_alter_table("outbox_events") as batch:
            batch.create_check_constraint(
                OUTBOX_ATTEMPTS_CHECK, OUTBOX_ATTEMPTS_PREDICATE
            )

    # --- uniqueness -------------------------------------------------------
    # Both guarantees are indexes rather than table constraints so SQLite needs
    # no table rebuild for them, and so the emitted DDL matches the models.
    #
    # The recovery-case guarantee is *filtered*. A payment legitimately keeps
    # every terminal case it ever had, so unique ``payment_id`` would reject valid
    # history; what must never happen twice is an open case, which is the
    # invariant ``RiskDetector`` already relies on when it reuses one instead of
    # opening a second. SQLite 3.8.0+ and PostgreSQL both support partial indexes,
    # so the guarantee is identical on either engine.
    if OPEN_RECOVERY_CASE_INDEX not in case_indexes:
        op.create_index(
            OPEN_RECOVERY_CASE_INDEX,
            "recovery_cases",
            ["payment_id"],
            unique=True,
            sqlite_where=sa.text(OPEN_RECOVERY_CASE_PREDICATE),
            postgresql_where=sa.text(OPEN_RECOVERY_CASE_PREDICATE),
        )
    # Re-read: a SQLite batch rebuild of ``payment_attempts`` recreates its
    # indexes, so the pre-DDL snapshot is no longer authoritative here.
    if PAYMENT_ATTEMPT_UNIQUE_INDEX not in _index_names(
        sa.inspect(connection), "payment_attempts"
    ):
        op.create_index(
            PAYMENT_ATTEMPT_UNIQUE_INDEX,
            "payment_attempts",
            ["payment_id", "attempt_number"],
            unique=True,
        )

    # --- immutable audit trail --------------------------------------------
    # ``audit_events`` keeps its existing unique ``(case_id, sequence)`` index and
    # is not rebuilt, so no historical row is rewritten. It gains only a guard
    # that refuses to update recorded content or sequence. The statements are
    # themselves idempotent, so a bootstrapped database that already installed the
    # guard is left with exactly one.
    for statement in audit_immutability_statements(dialect):
        op.execute(statement)


def downgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name
    inspector = sa.inspect(connection)

    for statement in drop_audit_immutability_statements(dialect):
        op.execute(statement)

    # Mirrors ``upgrade``: drop only what is actually present, so downgrading a
    # database that reached this revision partly through the bootstrap path does
    # not fail on a constraint that was never installed here.
    if OUTBOX_ATTEMPTS_CHECK in _check_names(inspector, "outbox_events"):
        with op.batch_alter_table("outbox_events") as batch:
            batch.drop_constraint(OUTBOX_ATTEMPTS_CHECK, type_="check")

    job_checks = _check_names(inspector, "background_jobs")
    job_keys = _foreign_key_names(inspector, "background_jobs")
    if job_checks or JOB_CASE_FOREIGN_KEY in job_keys:
        with op.batch_alter_table("background_jobs") as batch:
            if JOB_CASE_FOREIGN_KEY in job_keys:
                batch.drop_constraint(JOB_CASE_FOREIGN_KEY, type_="foreignkey")
            if JOB_ATTEMPT_BOUNDS_CHECK in job_checks:
                batch.drop_constraint(JOB_ATTEMPT_BOUNDS_CHECK, type_="check")
            if JOB_STATUS_CHECK in job_checks:
                batch.drop_constraint(JOB_STATUS_CHECK, type_="check")

    if RECOVERY_OUTCOME_AMOUNT_CHECK in _check_names(inspector, "recovery_outcomes"):
        with op.batch_alter_table("recovery_outcomes") as batch:
            batch.drop_constraint(RECOVERY_OUTCOME_AMOUNT_CHECK, type_="check")

    if ACTION_PAYMENT_FOREIGN_KEY in _foreign_key_names(inspector, "recovery_actions"):
        with op.batch_alter_table("recovery_actions") as batch:
            batch.drop_constraint(ACTION_PAYMENT_FOREIGN_KEY, type_="foreignkey")

    if PAYMENT_ATTEMPT_NUMBER_CHECK in _check_names(inspector, "payment_attempts"):
        with op.batch_alter_table("payment_attempts") as batch:
            batch.drop_constraint(PAYMENT_ATTEMPT_NUMBER_CHECK, type_="check")

    if PAYMENT_ATTEMPT_UNIQUE_INDEX in _index_names(
        sa.inspect(connection), "payment_attempts"
    ):
        op.drop_index(PAYMENT_ATTEMPT_UNIQUE_INDEX, table_name="payment_attempts")
    if OPEN_RECOVERY_CASE_INDEX in _index_names(inspector, "recovery_cases"):
        op.drop_index(OPEN_RECOVERY_CASE_INDEX, table_name="recovery_cases")


__all__ = ["ReadinessIntegrityPreflightError"]
