"""Claim and execute at most one due RevivePay DB job (safe worker smoke command)."""

from __future__ import annotations
import socket

from app.core.config import get_settings
from app.core.container import get_clock
from app.db.session import session_scope
from app.services.job_service import JobService


def main() -> None:
    settings = get_settings()
    with session_scope() as session:
        service = JobService(session, get_clock(settings), settings)
        job = service.claim_due(f"{socket.gethostname()}-worker")
        if job is None:
            print("no due jobs")
            return
        service.execute_claimed(job)
        print(f"completed {job.job_id}: {job.status}")


if __name__ == "__main__":
    main()
