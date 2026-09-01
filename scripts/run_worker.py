"""Long-running database worker for production containers."""
from __future__ import annotations
import os
import socket
import time
from app.core.config import get_settings
from app.core.container import get_clock
from app.db.session import session_scope
from app.services.job_service import JobService

def main() -> None:
    settings = get_settings()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
        with session_scope() as session:
            service = JobService(session, get_clock(settings), settings)
            job = service.claim_due(worker_id)
            if job is not None:
                service.execute_claimed(job)
                continue
        time.sleep(2)

if __name__ == "__main__":
    main()
