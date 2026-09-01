"""DB-backed job/outbox boundary that invokes, but never replaces, the workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.logging import log_context
from app.db.base import new_id
from app.models import BackgroundJob, OutboxEvent
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow


class JobService:
    RECOVERY_JOB = "RECOVERY_RUN"

    def __init__(self, session: Session, clock: VirtualClock, settings: Settings) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def enqueue_recovery(self, case_id: str, *, idempotency_key: str, request_id: str | None = None) -> BackgroundJob:
        """Persist job and outbox event in the caller's transaction."""
        existing = self._session.execute(select(BackgroundJob).where(BackgroundJob.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing is not None:
            return existing
        now = self._now()
        job = BackgroundJob(job_id=new_id("job"), job_type=self.RECOVERY_JOB, case_id=case_id, idempotency_key=idempotency_key, status="PENDING", payload={"case_id": case_id}, attempts=0, max_attempts=self._settings.worker_max_attempts, available_at=now, request_id=request_id, created_at=now, updated_at=now)
        event = OutboxEvent(event_id=new_id("out"), aggregate_type="RecoveryCase", aggregate_id=case_id, event_type="RECOVERY_RUN_QUEUED", idempotency_key=f"outbox:{idempotency_key}", payload={"job_id": job.job_id, "case_id": case_id}, request_id=request_id, attempts=0, created_at=now)
        self._session.add_all((job, event))
        self._session.flush()
        return job

    def claim_due(self, worker_id: str) -> BackgroundJob | None:
        """Lease one due job. Conditional update makes SQLite's single-worker path safe."""
        now = self._now()
        candidate = self._session.execute(select(BackgroundJob).where(BackgroundJob.status.in_(("PENDING", "RETRY")), BackgroundJob.available_at <= now, or_(BackgroundJob.lease_expires_at.is_(None), BackgroundJob.lease_expires_at < now)).order_by(BackgroundJob.available_at, BackgroundJob.job_id).limit(1)).scalar_one_or_none()
        if candidate is None:
            return None
        claimed = self._session.execute(update(BackgroundJob).where(BackgroundJob.job_id == candidate.job_id, BackgroundJob.status.in_(("PENDING", "RETRY"))).values(status="RUNNING", lease_owner=worker_id, lease_expires_at=now + timedelta(seconds=self._settings.worker_lease_seconds), attempts=BackgroundJob.attempts + 1, updated_at=now))
        if claimed.rowcount != 1:
            self._session.rollback()
            return None
        self._session.commit()
        return self._session.get(BackgroundJob, candidate.job_id)

    def execute_claimed(self, job: BackgroundJob) -> BackgroundJob:
        if job.status != "RUNNING" or job.job_type != self.RECOVERY_JOB or not job.case_id:
            return job
        try:
            with log_context(request_id=job.request_id, job_id=job.job_id):
                run = RevenueRecoveryWorkflow(self._session, self._clock, settings=self._settings).run(job.case_id)
                job.status = "COMPLETED"
                job.result = {"workflow_id": run.workflow_id, "final_status": run.final_status.value, "recovered_amount": run.recovered_amount}
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = self._now()
                self._session.commit()
        except Exception as error:
            self._session.rollback()
            job = self._session.get(BackgroundJob, job.job_id)
            if job is None:
                raise
            job.last_error = type(error).__name__
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = self._now()
            job.status = "FAILED" if job.attempts >= job.max_attempts else "RETRY"
            job.available_at = self._now() + timedelta(seconds=min(60, job.attempts * 5))
            self._session.commit()
            raise
        return job
