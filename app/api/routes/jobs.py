"""Protected durable job submission and status routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.api.auth import OperationsPrincipalDep
from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.core.errors import RecordNotFound, RevivePayError
from app.models import BackgroundJob, RecoveryCase
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


class IdempotencyKeyRequired(RevivePayError):
    code = "IDEMPOTENCY_KEY_REQUIRED"
    http_status = 422

    def __init__(self) -> None:
        super().__init__("Idempotency-Key is required when submitting durable work.")


def _read(job: BackgroundJob) -> dict:
    return {"job_id": job.job_id, "job_type": job.job_type, "case_id": job.case_id, "status": job.status, "attempts": job.attempts, "max_attempts": job.max_attempts, "request_id": job.request_id, "result": job.result, "created_at": job.created_at, "updated_at": job.updated_at}


@router.post("/recovery/{case_id}", status_code=status.HTTP_202_ACCEPTED, summary="Queue one idempotent recovery run")
def enqueue_recovery(case_id: str, request: Request, session: SessionDep, clock: ClockDep, settings: SettingsDep, _: OperationsPrincipalDep, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> dict:
    if not idempotency_key:
        raise IdempotencyKeyRequired()
    if session.get(RecoveryCase, case_id) is None:
        raise RecordNotFound("RecoveryCase", case_id)
    job = JobService(session, clock, settings).enqueue_recovery(case_id, idempotency_key=idempotency_key, request_id=getattr(request.state, "request_id", None))
    session.commit()
    return _read(job)


@router.get("/{job_id}", summary="Read durable job status")
def get_job(job_id: str, session: SessionDep, _: OperationsPrincipalDep) -> dict:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        raise RecordNotFound("BackgroundJob", job_id)
    return _read(job)
