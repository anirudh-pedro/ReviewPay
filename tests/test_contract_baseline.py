"""Protected-contract baseline regression tests.

These tests are the guard that later readiness phases cannot silently change
deterministic recovery behaviour. Integrity migrations, the database Virtual Clock,
the job and outbox lifecycles, and source cleanup all land after this point; each of
them touches persistence or wiring that the recovery pipeline runs on. A change that
alters a decision, a policy verdict, an Expected Recovery Value, a simulated outcome,
a verified outcome, an audit sequence, a public response field, or the error envelope
must fail here rather than pass quietly.

Every comparison runs against unchanged seeded inputs, unchanged configuration, and
a Virtual Clock reset to the configured simulation start, so a failure means the
behaviour moved rather than the fixture drifting (Requirement 3.1, 15.2).

Nothing here mutates production behaviour, routes, or response models. A mismatch is
not something to "fix" by rewriting the recorded baseline: Requirement 3.5 requires
an approved migration and compatibility record identifying the intentional change
and its validation evidence before the baseline moves.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 15.1, 15.2
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest

from app.core.enums import AuditEventType, CaseState
from tests.contract_baseline import (
    DEMO_CASE_IDS,
    ERROR_ENVELOPE_SPECS,
    SCHEMA_VERSION,
    SEEDED_READ_ENDPOINTS,
    SETTLED_READ_ENDPOINTS,
    configuration_snapshot,
    contains_volatile_values,
    drive_case,
    error_envelope_snapshot,
    field_paths,
    load_recorded_baseline,
    response_field_snapshot,
    scenarios_snapshot,
    seed_demo_scenarios,
    simulator_snapshot,
    write_recorded_baseline,
)

#: Set to regenerate the committed record. Deliberately opt-in: a baseline that
#: rewrote itself on mismatch would record a regression instead of catching it.
WRITE_MODE = os.environ.get("REVIVEPAY_WRITE_CONTRACT_BASELINE") == "1"

#: The only calendar date any recorded moment may fall on, because simulation time
#: starts there and moves only when a test advances it.
SIMULATION_DATE = "2026-01-01"

_ISO_MOMENT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

_MISMATCH_HELP = (
    "A protected contract changed. Requirement 3.5 requires an approved migration "
    "and compatibility record identifying the intentional change and its validation "
    "evidence before this baseline is updated. Do not regenerate the record to make "
    "this pass."
)

_captured: dict[str, Any] = {}


def _recorded() -> dict[str, Any]:
    try:
        return load_recorded_baseline()
    except FileNotFoundError:  # pragma: no cover - only before first generation
        pytest.fail(
            "The protected-contract baseline record is missing. Generate it once with "
            "REVIVEPAY_WRITE_CONTRACT_BASELINE=1 and commit it as release evidence."
        )


@pytest.fixture(scope="session", autouse=True)
def _baseline_record_writer():
    """Persist the merged record when regeneration is explicitly requested."""
    if WRITE_MODE:
        try:
            _captured.update(load_recorded_baseline())
        except FileNotFoundError:
            _captured["schema_version"] = SCHEMA_VERSION
    yield
    if WRITE_MODE and _captured:
        _captured["schema_version"] = SCHEMA_VERSION
        write_recorded_baseline(_captured)


def _check(section: str, live: Any, *, key: str | None = None) -> None:
    """Compare one snapshot section against the recorded baseline."""
    if key is None:
        _captured[section] = live
    else:
        _captured.setdefault(section, {})[key] = live

    if WRITE_MODE:
        return

    recorded = _recorded()
    assert section in recorded, f"baseline section '{section}' is missing. {_MISMATCH_HELP}"
    expected = recorded[section]
    if key is not None:
        assert key in expected, f"baseline '{section}.{key}' is missing. {_MISMATCH_HELP}"
        expected = expected[key]

    label = section if key is None else f"{section}.{key}"
    assert live == expected, f"{label} does not match the recorded baseline. {_MISMATCH_HELP}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(db, clock, settings):
    """The four demo scenarios, seeded and still runnable."""
    return seed_demo_scenarios(db, clock, settings)


@pytest.fixture
def driven(db, clock, settings) -> dict[str, Any]:
    """The four demo scenarios driven to their terminal states."""
    return scenarios_snapshot(db, clock, settings)


@pytest.fixture
def settled(db, clock, settings) -> None:
    """Seeded scenarios driven to terminal states, without keeping the snapshot.

    Used by the HTTP tests, which need populated optional response objects (latest
    action, policy verdict, verified outcome) rather than the snapshot itself.
    """
    seed_demo_scenarios(db, clock, settings)
    for case_id in sorted(DEMO_CASE_IDS.values()):
        drive_case(db, clock, settings, case_id)


# ===========================================================================
# 1. Inputs and configuration
# ===========================================================================


def test_seeded_configuration_matches_baseline(settings):
    """The inputs every other snapshot depends on (Requirement 3.1).

    Recorded first so a downstream mismatch can be attributed to behaviour rather
    than to a quietly changed default.
    """
    _check("configuration", configuration_snapshot(settings))


# ===========================================================================
# 2. Payment Simulator
# ===========================================================================


def test_payment_simulator_outcomes_match_baseline(db, clock, settings):
    """Scripted and seeded-draw outcomes for every reason/action/attempt.

    Requirement 3.1: the simulator's outcomes are protected behaviour. This exercises
    the simulator's own read-only decision path, so it cannot pass against a second
    model of the same logic.
    """
    _check("simulator", simulator_snapshot(db, clock, settings))


# ===========================================================================
# 3. Deterministic recovery: decisions, policy, ERV, verification, audit
# ===========================================================================


@pytest.mark.parametrize("scenario_key", sorted(DEMO_CASE_IDS))
def test_scenario_recovery_behaviour_matches_baseline(driven, scenario_key):
    """Decision, policy verdict, ERV breakdown, execution, outcome, audit order.

    One scenario per parameter so a failure names the scenario that moved
    (Requirement 3.1, 15.2).
    """
    _check("scenarios", driven[scenario_key], key=scenario_key)


def test_every_scenario_reaches_its_expected_terminal_state(driven):
    """The four scenarios still demonstrate what they were built to demonstrate."""
    assert driven["A"]["final_state"] == CaseState.RECOVERED.value
    assert driven["B"]["final_state"] == CaseState.STOPPED.value
    assert driven["C"]["final_state"] == CaseState.ESCALATED.value
    assert driven["D"]["final_state"] == CaseState.RECOVERED.value


def test_audit_sequences_are_gapless_and_strictly_increasing(driven):
    """Requirement 3.1: per-case audit ordering is protected behaviour.

    Asserted as an invariant as well as a snapshot. A snapshot alone would accept a
    renumbered trail as long as the new numbering was recorded; this will not.
    """
    for key, scenario in sorted(driven.items()):
        sequences = [event["sequence"] for event in scenario["audit_events"]]
        assert sequences, f"scenario {key} recorded no audit events"
        assert sequences == list(range(1, len(sequences) + 1)), (
            f"scenario {key} audit sequence is not dense and increasing: {sequences}"
        )

        timestamps = [event["timestamp"] for event in scenario["audit_events"]]
        assert timestamps == sorted(timestamps), (
            f"scenario {key} audit events are not returned oldest first"
        )


def test_no_recovered_claim_without_a_verified_outcome(driven):
    """Requirement 3.1: recovery remains a verified claim, not a reported one."""
    for key, scenario in sorted(driven.items()):
        recovered_runs = [
            run for run in scenario["runs"] if run["recovered_amount"] > 0
        ]
        for run in recovered_runs:
            assert run["outcome"] is not None, f"scenario {key} claimed recovery with no outcome"
            assert run["outcome"]["recovered"] is True
            assert run["outcome"]["recovered_amount"] == run["recovered_amount"]

        event_types = [event["event_type"] for event in scenario["audit_events"]]
        if scenario["final_state"] == CaseState.RECOVERED.value:
            assert AuditEventType.OUTCOME_VERIFIED.value in event_types
            assert AuditEventType.REVENUE_RECOVERED.value in event_types
        else:
            assert AuditEventType.REVENUE_RECOVERED.value not in event_types


# ===========================================================================
# 4. Public response fields
# ===========================================================================


def test_public_response_fields_match_baseline(settled, api_client, api_prefix):
    """Requirement 3.4: existing response fields are preserved for consumers."""
    specs = tuple((method, template, None) for method, template in SETTLED_READ_ENDPOINTS)
    _check(
        "public_response_fields",
        response_field_snapshot(api_client, api_prefix, specs),
    )


def test_runnable_case_response_fields_match_baseline(seeded, api_client, api_prefix):
    """The read-only surfaces that need a case which has not yet terminated."""
    _check(
        "runnable_case_response_fields",
        response_field_snapshot(api_client, api_prefix, SEEDED_READ_ENDPOINTS),
    )


def test_autopilot_response_fields_match_baseline(seeded, api_client, api_prefix):
    """Requirement 3.3: the Autopilot batch contract is preserved.

    Snapshotted from its own seeded database because the call drives every pending
    case to a terminal state.
    """
    response = api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    assert response.status_code == 200

    _check(
        "autopilot_response_fields",
        {
            "status_code": response.status_code,
            "fields": sorted(field_paths(response.json())),
        },
    )


# ===========================================================================
# 5. Standard error envelope
# ===========================================================================


def test_error_envelope_matches_baseline(settled, api_client, api_prefix):
    """Requirement 3.4: error-envelope semantics are preserved."""
    _check("error_envelope", error_envelope_snapshot(api_client, api_prefix))


def test_error_envelope_semantics_hold_independently(settled, api_client, api_prefix):
    """The envelope shape asserted directly, not only against the record.

    Status code, ``error.code``, and the two-field envelope are the contract existing
    consumers depend on, so they are checked without reference to the snapshot.
    """
    for label, method, template, body, status, code in ERROR_ENVELOPE_SPECS:
        path = template.format(prefix=api_prefix)
        response = (
            api_client.get(path)
            if method == "GET"
            else api_client.post(path, json=body if body is not None else {})
        )

        assert response.status_code == status, f"{label} returned {response.status_code}"
        payload = response.json()
        assert set(payload) == {"error"}, f"{label} envelope has extra top-level fields"
        assert set(payload["error"]) == {"code", "message"}, f"{label} envelope shape changed"
        assert payload["error"]["code"] == code, f"{label} error code changed"
        assert isinstance(payload["error"]["message"], str)
        assert payload["error"]["message"], f"{label} returned an empty message"


# ===========================================================================
# 6. The record itself must be machine- and wall-clock-independent
# ===========================================================================


def test_recorded_baseline_carries_no_generated_identifiers():
    """Workflow, action, event, and outcome ids are generated per run.

    Recording one would make the baseline fail on the next machine for a reason that
    has nothing to do with behaviour.
    """
    offenders = contains_volatile_values(_recorded())
    assert offenders == [], f"generated identifiers recorded in the baseline: {offenders}"


def test_recorded_baseline_moments_all_fall_on_the_simulated_date():
    """No recorded moment may come from the wall clock (Requirement 3.1)."""
    offenders: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                _walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and _ISO_MOMENT.match(node):
            if not node.startswith(SIMULATION_DATE):
                offenders.append(f"{path}={node}")

    _walk(_recorded(), "")
    assert offenders == [], f"non-simulated moments recorded in the baseline: {offenders}"


def test_recorded_baseline_declares_its_schema_version():
    assert _recorded()["schema_version"] == SCHEMA_VERSION
