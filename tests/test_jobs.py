"""Durable DB job/outbox and claim idempotency contracts."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import BackgroundJob, OutboxEvent
from app.services.job_service import JobService


def test_enqueue_is_idempotent_and_writes_job_and_outbox_together(db, clock, settings):
    service = JobService(db, clock, settings)
    first = service.enqueue_recovery("case_demo", idempotency_key="request-001", request_id="req-001")
    second = service.enqueue_recovery("case_demo", idempotency_key="request-001", request_id="req-001")
    db.commit()

    assert first.job_id == second.job_id
    assert db.execute(select(func.count()).select_from(BackgroundJob)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(OutboxEvent)).scalar_one() == 1
    assert first.status == "PENDING"


def test_only_one_worker_claims_a_pending_job(db, clock, settings):
    service = JobService(db, clock, settings)
    queued = service.enqueue_recovery("case_demo", idempotency_key="request-002")
    db.commit()

    claimed = service.claim_due("worker-a")
    duplicate = service.claim_due("worker-b")

    assert claimed is not None and claimed.job_id == queued.job_id
    assert claimed.status == "RUNNING"
    assert duplicate is None


def test_job_api_requires_key_and_deduplicates_submission(api_client, api_prefix):
    api_client.post(f"{api_prefix}/demo/reset", json={})
    missing = api_client.post(f"{api_prefix}/jobs/recovery/case_demo_a", headers={})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    headers = {"Idempotency-Key": "api-job-001"}
    first = api_client.post(f"{api_prefix}/jobs/recovery/case_demo_a", headers=headers)
    second = api_client.post(f"{api_prefix}/jobs/recovery/case_demo_a", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert api_client.get(f"{api_prefix}/jobs/{first.json()['job_id']}").json()["status"] == "PENDING"
