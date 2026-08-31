"""Recovery case endpoints (Requirement 24.3).

Thin handlers. The one substantive endpoint, ``POST /recovery/cases/{id}/run``,
delegates a whole recovery cycle to the workflow and serializes what came back
(Requirement 1.9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import ClockDep, PaginationDep, SessionDep, SettingsDep
from app.core.enums import CaseState
from app.core.errors import RecordNotFound
from app.models import Payment, RecoveryAction, RecoveryCase
from app.schemas.common import Money, Page
from app.schemas.recovery import (
    AuditEventRead,
    AuditTrailResponse,
    DecisionExplanationRead,
    DiagnosisRead,
    ExecutionResultRead,
    PolicyResultRead,
    RecoveryActionRead,
    RecoveryCaseDetail,
    RecoveryCaseSummary,
    RecoveryOutcomeRead,
    WorkflowRunResponse,
)
from app.services.audit_service import AuditService
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _get_case(session, case_id: str) -> RecoveryCase:
    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise RecordNotFound("RecoveryCase", case_id)
    return case


def _currency(session, payment_id: str) -> str:
    payment = session.get(Payment, payment_id)
    return payment.currency if payment else "INR"


def _action_read(action: RecoveryAction) -> RecoveryActionRead:
    return RecoveryActionRead(
        action_id=action.action_id,
        action_type=action.action_type,
        estimated_probability=action.estimated_probability,
        confidence=action.confidence,
        model_version=action.model_version,
        expected_recovery_value=action.expected_recovery_value,
        erv_breakdown=action.erv_breakdown or {},
        risk_level=action.risk_level,
        policy_outcome=action.policy_outcome,
        policy_rule_id=action.policy_rule_id,
        policy_reason=action.policy_reason,
        decision_explanation=action.decision_explanation or {},
        status=action.status,
        requires_human_approval=action.requires_human_approval,
        created_at=action.created_at,
        scheduled_at=action.scheduled_at,
        executed_at=action.executed_at,
    )


@router.get("/cases", response_model=Page[RecoveryCaseSummary], summary="List recovery cases")
def list_cases(
    session: SessionDep,
    pagination: PaginationDep,
    state: Annotated[CaseState | None, Query(description="Filter by case state.")] = None,
) -> Page[RecoveryCaseSummary]:
    total_statement = select(func.count()).select_from(RecoveryCase)
    items_statement = select(RecoveryCase).order_by(
        RecoveryCase.created_at.desc(), RecoveryCase.case_id
    )

    if state is not None:
        total_statement = total_statement.where(RecoveryCase.state == state)
        items_statement = items_statement.where(RecoveryCase.state == state)

    total = int(session.execute(total_statement).scalar_one())
    cases = list(
        session.execute(items_statement.limit(pagination.limit).offset(pagination.offset))
        .scalars()
        .all()
    )

    return Page[RecoveryCaseSummary](
        items=[
            RecoveryCaseSummary.from_model(case, _currency(session, case.payment_id))
            for case in cases
        ],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/cases/{case_id}",
    response_model=RecoveryCaseDetail,
    summary="Get a recovery case with its decision explanation",
)
def get_case(case_id: str, session: SessionDep) -> RecoveryCaseDetail:
    """Requirement 12.4: returns the explanation for the most recent action."""
    case = _get_case(session, case_id)
    currency = _currency(session, case.payment_id)

    actions = sorted(case.actions, key=lambda item: (item.created_at, item.action_id))
    latest = actions[-1] if actions else None

    explanation = None
    if latest is not None and latest.decision_explanation:
        explanation = DecisionExplanationRead.model_validate(latest.decision_explanation)

    policy = None
    if latest is not None and latest.policy_outcome is not None:
        policy = PolicyResultRead(
            outcome=latest.policy_outcome,
            rule_id=latest.policy_rule_id or "",
            reason=latest.policy_reason or "",
        )

    outcome = None
    if latest is not None and latest.outcome is not None:
        outcome = RecoveryOutcomeRead.model_validate(latest.outcome)

    waiting_until = None
    if latest is not None and latest.scheduled_at is not None and latest.executed_at is None:
        waiting_until = latest.scheduled_at

    summary = RecoveryCaseSummary.from_model(case, currency)
    return RecoveryCaseDetail(
        **summary.model_dump(),
        diagnosis=DiagnosisRead.model_validate(case.diagnosis) if case.diagnosis else None,
        latest_action=_action_read(latest) if latest else None,
        latest_explanation=explanation,
        latest_policy=policy,
        latest_outcome=outcome,
        actions=[_action_read(action) for action in actions],
        waiting_until=waiting_until,
        is_terminal=case.is_terminal,
    )


@router.post(
    "/cases/{case_id}/run",
    response_model=WorkflowRunResponse,
    summary="Run one recovery cycle",
)
def run_case(
    case_id: str,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> WorkflowRunResponse:
    """Perform exactly one decide, gate, execute, verify cycle.

    Returns 404 for an unknown case and 409 for a terminal one
    (Requirement 24.8, 24.9).
    """
    _get_case(session, case_id)

    workflow = RevenueRecoveryWorkflow(session=session, clock=clock, settings=settings)
    run = workflow.run(case_id)

    return WorkflowRunResponse(
        workflow_id=run.workflow_id,
        case_id=run.case_id,
        payment_id=run.payment_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        state=run.state,
        final_status=run.final_status,
        selected_action=run.selected_action,
        explanation=(
            DecisionExplanationRead.model_validate(run.decision.explanation.to_dict())
            if run.decision is not None
            else None
        ),
        policy=(
            PolicyResultRead(
                outcome=run.policy.outcome,
                rule_id=run.policy.rule_id,
                reason=run.policy.reason,
            )
            if run.policy is not None
            else None
        ),
        execution=(
            ExecutionResultRead(
                action=run.execution.action,
                status=run.execution.status,
                provider_response=run.execution.provider_response,
                executed_at=run.execution.executed_at,
            )
            if run.execution is not None
            else None
        ),
        outcome=(
            RecoveryOutcomeRead.model_validate(run.outcome)
            if run.outcome is not None
            else None
        ),
        recovered_amount=Money.of(run.recovered_amount, run.currency),
        waiting_until=run.waiting_until,
        stages=list(run.stages),
        message=run.message,
    )


@router.get(
    "/cases/{case_id}/audit",
    response_model=AuditTrailResponse,
    summary="Get a case's complete audit trail",
)
def get_case_audit(case_id: str, session: SessionDep, clock: ClockDep) -> AuditTrailResponse:
    """Requirement 19.7: oldest first."""
    case = _get_case(session, case_id)
    events = AuditService(session=session, clock=clock).for_case(case.case_id)

    return AuditTrailResponse(
        case_id=case.case_id,
        events=[AuditEventRead.from_model(event) for event in events],
        total=len(events),
    )
