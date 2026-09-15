"""Worker CLI entry point for Docker and standalone execution."""

from __future__ import annotations

import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    from resiliencelab.controlplane.worker import run_worker

    worker_id = os.environ.get("RESILIENCELAB_WORKER_ID")
    redis_url = os.environ.get("RESILIENCELAB_REDIS_URL")
    db_url = os.environ.get("RESILIENCELAB_DATABASE_URL")
    max_jobs = os.environ.get("RESILIENCELAB_WORKER_MAX_JOBS")

    run_worker(
        worker_id=worker_id,
        redis_url=redis_url,
        db_url=db_url,
        max_jobs=int(max_jobs) if max_jobs else None,
    )


if __name__ == "__main__":
    main()
