"""Protected-contract baseline snapshot builders.

This module is a **fixture library, not a test module**. It builds deterministic
snapshots of the behaviour that later readiness phases (integrity migrations, the
database Virtual Clock, job/outbox lifecycles, and source cleanup) must not change:

- deterministic decisions and the selected action
- Policy Engine outcomes, rule ids, and reasons
- Expected Recovery Value totals and their full breakdown fields
- Payment Simulator outcomes and how each one was decided
- Outcome Verifier results
- per-case Audit Event ordering and sequence
- public API response field names for the key endpoints
- the standard error-envelope shape

Determinism rules that every builder here obeys (Requirement 3.1, 15.2):

1. Only the seeded synthetic demo scenarios are used, so the inputs are fixed.
2. Time comes from the injected :class:`~app.core.clock.VirtualClock` and is reset
   to the configured simulation start before each scenario, so a scenario snapshot
   never depends on how many other scenarios ran first.
3. Generated identifiers (``wf_``, ``act_``, ``evt_``, ``out_``) and wall-clock
   values are excluded. Anything a machine or a clock could vary is left out
   rather than recorded and tolerated.

The recorded snapshot lives beside this module in
``tests/baseline/protected_contract_baseline.json``. It is committed evidence, so it
is regenerated only alongside the approved compatibility record Requirement 3.5
demands::

    REVIVEPAY_WRITE_CONTRACT_BASELINE=1 python -m pytest tests/test_contract_baseline.py
    python -m pytest tests/test_contract_baseline.py

The record is written at session teardown, so the first command reports the checks
that inspect the record as failing; the second command is what confirms the new
record. Regeneration deliberately requires that opt-in: a baseline that rewrote
itself on mismatch would record the regression instead of catching it.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 15.1, 15.2
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.enums import ActionType, FailureReason
from app.integrations.payment_simulator import PaymentSimulatorExecutor
from app.models import RecoveryCase
from app.services.audit_service import AuditService
from app.services.policy_rules import RULE_ORDER
from app.services.scenario_generator import ScenarioGenerator
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

#: The committed baseline record.
BASELINE_PATH = (
    Path(__file__).resolve().parent / "baseline" / "protected_contract_baseline.json"
)

#: The four deterministic demo scenarios, keyed by the case ids the seeder assigns.
DEMO_CASE_IDS: dict[str, str] = {
    "A": "case_demo_a",
    "B": "case_demo_b",
    "C": "case_demo_c",
    "D": "case_demo_d",
}

#: Hard ceiling on runs per scenario. Every scenario must terminate well inside it;
#: exceeding it is itself a regression rather than something to snapshot.
MAX_RUNS_PER_SCENARIO = 8

#: Fixed probe inputs for the simulator decision matrix. A stable payment id keeps
#: the seeded hash draw reproducible on any machine.
SIMULATOR_PROBE_PAYMENT_ID = "pay_contract_baseline_probe"
SIMULATOR_PROBE_ATTEMPTS = (1, 2, 3)

#: Read-only endpoints snapshotted once every demo scenario has reached a terminal
#: state, so optional nested objects (latest action, policy, outcome) are populated.
SETTLED_READ_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/health"),
    ("GET", "/readyz"),
    ("GET", "{prefix}/recovery/overview"),
    ("GET", "{prefix}/recovery/scenarios"),
    ("GET", "{prefix}/recovery/baseline"),
    ("GET", "{prefix}/recovery/cases"),
    ("GET", "{prefix}/recovery/cases/case_demo_a"),
    ("GET", "{prefix}/recovery/cases/case_demo_a/audit"),
    ("GET", "{prefix}/analytics/revenue"),
    ("GET", "{prefix}/analytics/recovery"),
    ("GET", "{prefix}/payments"),
    ("GET", "{prefix}/payments/pay_demo_a"),
    ("GET", "{prefix}/simulate/clock"),
)

#: Read-only endpoints that need a runnable (non-terminal) case.
SEEDED_READ_ENDPOINTS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "{prefix}/recovery/cases/case_demo_a/intelligence", None),
    ("POST", "{prefix}/recovery/cases/case_demo_a/simulate", {}),
)

#: Error cases that must keep the standard envelope (Requirement 3.4).
#: ``(label, method, path, body, expected_status, expected_code)``
ERROR_ENVELOPE_SPECS: tuple[
    tuple[str, str, str, dict[str, Any] | None, int, str], ...
] = (
    (
        "unknown_case",
        "GET",
        "{prefix}/recovery/cases/case_does_not_exist",
        None,
        404,
        "NOT_FOUND",
    ),
    (
        "unknown_payment",
        "GET",
        "{prefix}/payments/pay_does_not_exist",
        None,
        404,
        "NOT_FOUND",
    ),
    (
        "invalid_clock_advance",
        "POST",
        "{prefix}/simulate/advance-clock",
        {"minutes": -5},
        422,
        "VALIDATION_ERROR",
    ),
    (
        "empty_clock_advance",
        "POST",
        "{prefix}/simulate/advance-clock",
        {},
        422,
        "VALIDATION_ERROR",
    ),
    (
        "terminal_case_run",
        "POST",
        "{prefix}/recovery/cases/case_demo_a/run",
        {},
        409,
        "CASE_TERMINAL",
    ),
)

#: Identifier prefixes that are generated per run and must never reach a snapshot.
VOLATILE_ID_PREFIXES = ("wf_", "act_", "evt_", "out_")


# ---------------------------------------------------------------------------
# Recorded baseline access
# ---------------------------------------------------------------------------


def load_recorded_baseline() -> dict[str, Any]:
    """Read the committed baseline record."""
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_recorded_baseline(snapshot: dict[str, Any]) -> Path:
    """Persist a baseline record. Used only by the explicit regeneration command."""
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return BASELINE_PATH


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


# ---------------------------------------------------------------------------
# Configuration snapshot
# ---------------------------------------------------------------------------


def configuration_snapshot(settings: Settings) -> dict[str, Any]:
    """The seeded inputs and configuration every other snapshot depends on.

    Recorded so that a baseline mismatch can be attributed either to a behaviour
    change or to a configuration change, rather than leaving the two indistinguishable.
    """
    return {
        "simulation_seed": settings.simulation_seed,
        "virtual_clock_start": _iso(settings.virtual_clock_start),
        "retry_later_delay_minutes": settings.retry_later_delay_minutes,
        "max_automatic_retries": settings.max_automatic_retries,
        "repeated_failure_limit": settings.repeated_failure_limit,
        "high_value_escalation_threshold": settings.high_value_escalation_threshold,
        "allow_human_escalation": settings.allow_human_escalation,
        "default_currency": settings.default_currency,
        "diagnosis_engine_impl": settings.diagnosis_engine_impl,
        "recovery_predictor_impl": settings.recovery_predictor_impl,
        "action_executor_impl": settings.action_executor_impl,
        "simulator_fallback_probability": settings.simulator_fallback_probability,
        "intervention_cost_minor": {
            action.value: settings.intervention_cost(action) for action in ActionType
        },
        "friction_penalty_minor": {
            action.value: settings.friction_penalty(action) for action in ActionType
        },
        "policy_rule_order": list(RULE_ORDER),
    }


# ---------------------------------------------------------------------------
# Recovery behaviour snapshot
# ---------------------------------------------------------------------------


def _breakdown_snapshot(breakdown: Any) -> dict[str, Any]:
    """Full Expected Recovery Value arithmetic, not just the total."""
    return dict(breakdown.to_dict())


def _candidate_snapshot(candidate: Any) -> dict[str, Any]:
    return {
        "action": candidate.action.value,
        "probability": candidate.probability,
        "confidence": candidate.confidence,
        "expected_recovery_value": candidate.expected_recovery_value,
        "risk_level": candidate.risk_level.value,
        "breakdown": _breakdown_snapshot(candidate.breakdown),
    }


def decision_snapshot(decision: Any) -> dict[str, Any]:
    """Selected action, valuation, ranking, and the explanation behind it."""
    return {
        "selected_action": decision.selected_action.value,
        "probability": decision.probability,
        "confidence": decision.confidence,
        "expected_recovery_value": decision.expected_recovery_value,
        "risk_level": decision.risk_level.value,
        "model_version": decision.model_version,
        "breakdown": _breakdown_snapshot(decision.breakdown),
        "ranked": [_candidate_snapshot(item) for item in decision.ranked],
        "explanation": decision.explanation.to_dict(),
    }


def policy_snapshot(policy: Any) -> dict[str, Any]:
    """The verdict, the deciding rule, and the reason text."""
    return {
        "outcome": policy.outcome.value,
        "rule_id": policy.rule_id,
        "reason": policy.reason,
    }


def execution_snapshot(execution: Any) -> dict[str, Any]:
    """What the Payment Simulator reported, including how it decided."""
    return {
        "action": execution.action.value,
        "status": execution.status.value,
        "executed_at": _iso(execution.executed_at),
        "provider_response": json.loads(json.dumps(execution.provider_response)),
    }


def outcome_snapshot(outcome: Any) -> dict[str, Any]:
    """The independently verified outcome, read back from persisted payment state."""
    return {
        "previous_payment_status": outcome.previous_payment_status.value,
        "new_payment_status": outcome.new_payment_status.value,
        "recovered": outcome.recovered,
        "recovered_amount": outcome.recovered_amount,
        "failure_reason": (
            outcome.failure_reason.value if outcome.failure_reason else None
        ),
        "verification_timestamp": _iso(outcome.verification_timestamp),
    }


def run_snapshot(run: Any, *, run_index: int, entry_state: str) -> dict[str, Any]:
    """One complete decide/gate/execute/verify cycle."""
    return {
        "run_index": run_index,
        "entry_state": entry_state,
        "state": run.state.value,
        "final_status": run.final_status.value,
        "selected_action": (
            run.selected_action.value if run.selected_action is not None else None
        ),
        "recovered_amount": run.recovered_amount,
        "currency": run.currency,
        "started_at": _iso(run.started_at),
        "ended_at": _iso(run.ended_at),
        "waiting_until": _iso(run.waiting_until),
        "stages": list(run.stages),
        "decision": decision_snapshot(run.decision) if run.decision else None,
        "policy": policy_snapshot(run.policy) if run.policy else None,
        "execution": execution_snapshot(run.execution) if run.execution else None,
        "outcome": outcome_snapshot(run.outcome) if run.outcome else None,
    }


def audit_snapshot(session: Session, clock: VirtualClock, case_id: str) -> list[dict[str, Any]]:
    """Per-case Audit Event ordering: sequence, stage, type, and simulation time.

    Event ids are omitted deliberately; they are generated per write and carry no
    contract. Ordering and sequence are the protected properties (Requirement 3.1).
    """
    events = AuditService(session=session, clock=clock).for_case(case_id)
    return [
        {
            "sequence": event.sequence,
            "stage": event.stage.value,
            "event_type": event.event_type.value,
            "timestamp": _iso(event.timestamp),
        }
        for event in events
    ]


def seed_demo_scenarios(
    session: Session, clock: VirtualClock, settings: Settings
) -> dict[str, Any]:
    """Build the four deterministic demo scenarios with the real generator."""
    scenarios = ScenarioGenerator(
        session=session, clock=clock, settings=settings
    ).generate_demo_scenarios()
    session.commit()
    return {scenario.key: scenario for scenario in scenarios}


def drive_case(
    session: Session,
    clock: VirtualClock,
    settings: Settings,
    case_id: str,
) -> dict[str, Any]:
    """Run one case to a terminal state and snapshot everything it produced.

    Simulation time is reset to the configured start first, so this scenario's
    timeline is independent of any scenario driven before it. The clock is advanced
    only when the workflow reports that it is waiting for a scheduled action, which
    is the same thing an operator does by hand.
    """
    clock.reset(to=settings.virtual_clock_start)

    workflow = RevenueRecoveryWorkflow(session=session, clock=clock, settings=settings)
    runs: list[dict[str, Any]] = []
    clock_advances = 0

    for index in range(MAX_RUNS_PER_SCENARIO):
        case = session.get(RecoveryCase, case_id)
        if case is None:
            raise AssertionError(f"seeded case '{case_id}' is missing")
        if case.is_terminal:
            break

        entry_state = case.state.value
        run = workflow.run(case_id)
        runs.append(run_snapshot(run, run_index=index, entry_state=entry_state))

        if run.waiting:
            clock.advance(minutes=settings.retry_later_delay_minutes)
            clock_advances += 1

    case = session.get(RecoveryCase, case_id)
    if case is None or not case.is_terminal:
        raise AssertionError(
            f"case '{case_id}' did not terminate within {MAX_RUNS_PER_SCENARIO} runs"
        )

    return {
        "case_id": case.case_id,
        "payment_id": case.payment_id,
        "amount_at_risk": case.amount_at_risk,
        "final_state": case.state.value,
        "terminal_outcome": json.loads(json.dumps(case.terminal_outcome or {})),
        "diagnosis": json.loads(json.dumps(case.diagnosis or {})),
        "clock_advances": clock_advances,
        "runs": runs,
        "audit_events": audit_snapshot(session, clock, case.case_id),
    }


def scenarios_snapshot(
    session: Session, clock: VirtualClock, settings: Settings
) -> dict[str, Any]:
    """Drive all four seeded scenarios and snapshot each one."""
    seed_demo_scenarios(session, clock, settings)
    return {
        key: drive_case(session, clock, settings, case_id)
        for key, case_id in sorted(DEMO_CASE_IDS.items())
    }


# ---------------------------------------------------------------------------
# Payment Simulator snapshot
# ---------------------------------------------------------------------------


def simulator_snapshot(
    session: Session, clock: VirtualClock, settings: Settings
) -> dict[str, Any]:
    """Every ``(failure reason, action, attempt)`` outcome the simulator would give.

    Uses the simulator's own read-only decision path, so this records real
    behaviour rather than a second model of it. Nothing is persisted.
    """
    simulator = PaymentSimulatorExecutor(
        session=session, settings=settings, clock=clock
    )

    matrix: dict[str, Any] = {}
    for reason in FailureReason:
        for action in ActionType:
            for attempt in SIMULATOR_PROBE_ATTEMPTS:
                succeeded, basis = simulator.predict_outcome(
                    reason, action, SIMULATOR_PROBE_PAYMENT_ID, attempt
                )
                entry: dict[str, Any] = {
                    "succeeded": succeeded,
                    "decision_basis": basis["decision_basis"],
                }
                if "scripted_outcome" in basis:
                    entry["scripted_outcome"] = basis["scripted_outcome"]
                if "draw" in basis:
                    entry["draw"] = basis["draw"]
                    entry["success_threshold"] = basis["success_threshold"]
                    entry["seed"] = basis["seed"]
                matrix[f"{reason.value}:{action.value}:{attempt}"] = entry
    return matrix


# ---------------------------------------------------------------------------
# Public response field snapshot
# ---------------------------------------------------------------------------


def field_paths(payload: Any, prefix: str = "") -> set[str]:
    """Every field path in a JSON payload, with ``[]`` marking list nesting.

    Collection items contribute a union of their paths, so an added or renamed field
    is caught wherever it appears. Scalar list values contribute nothing, keeping
    this a snapshot of field *names* rather than data.
    """
    paths: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= field_paths(value, path)
    elif isinstance(payload, list):
        for item in payload:
            paths |= field_paths(item, f"{prefix}[]")
    return paths


def _request(client: Any, method: str, url: str, body: dict[str, Any] | None) -> Any:
    if method == "GET":
        return client.get(url)
    return client.post(url, json=body if body is not None else {})


def response_field_snapshot(
    client: Any,
    api_prefix: str,
    specs: tuple[tuple[str, str, dict[str, Any] | None], ...],
) -> dict[str, Any]:
    """Status code and field-name set for each public endpoint."""
    snapshot: dict[str, Any] = {}
    for method, template, body in specs:
        path = template.format(prefix=api_prefix)
        response = _request(client, method, path, body)
        snapshot[f"{method} {template}"] = {
            "status_code": response.status_code,
            "fields": sorted(field_paths(response.json())),
        }
    return snapshot


def error_envelope_snapshot(client: Any, api_prefix: str) -> dict[str, Any]:
    """The standard error envelope for each protected failure mode."""
    snapshot: dict[str, Any] = {}
    for label, method, template, body, _status, _code in ERROR_ENVELOPE_SPECS:
        path = template.format(prefix=api_prefix)
        response = _request(client, method, path, body)
        payload = response.json()
        snapshot[label] = {
            "status_code": response.status_code,
            "fields": sorted(field_paths(payload)),
            "code": payload.get("error", {}).get("code"),
        }
    return snapshot


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def build_recovery_baseline(
    session: Session, clock: VirtualClock, settings: Settings
) -> dict[str, Any]:
    """Configuration, scenario behaviour, and simulator matrix.

    Split out from the HTTP snapshot so property tests can reuse the deterministic
    recovery portion without standing up an application (Task 2.3).
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "configuration": configuration_snapshot(settings),
        "simulator": simulator_snapshot(session, clock, settings),
        "scenarios": scenarios_snapshot(session, clock, settings),
    }


def contains_volatile_values(snapshot: Any) -> list[str]:
    """Report any recorded value that a machine or a wall clock could vary."""
    offenders: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                _walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and node.startswith(VOLATILE_ID_PREFIXES):
            offenders.append(f"{path}={node}")

    _walk(snapshot, "")
    return offenders


__all__ = [
    "BASELINE_PATH",
    "DEMO_CASE_IDS",
    "ERROR_ENVELOPE_SPECS",
    "MAX_RUNS_PER_SCENARIO",
    "SCHEMA_VERSION",
    "SEEDED_READ_ENDPOINTS",
    "SETTLED_READ_ENDPOINTS",
    "audit_snapshot",
    "build_recovery_baseline",
    "configuration_snapshot",
    "contains_volatile_values",
    "decision_snapshot",
    "drive_case",
    "error_envelope_snapshot",
    "execution_snapshot",
    "field_paths",
    "load_recorded_baseline",
    "outcome_snapshot",
    "policy_snapshot",
    "response_field_snapshot",
    "run_snapshot",
    "scenarios_snapshot",
    "seed_demo_scenarios",
    "simulator_snapshot",
    "write_recorded_baseline",
]
