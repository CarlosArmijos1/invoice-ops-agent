"""Background worker: runs the scheduler until stopped.

uv run python -m opsagent.worker
"""

import signal
import threading

from opsagent.container import build_container
from opsagent.infra.logging import get_logger
from opsagent.scheduler.jobs import build_scheduler

log = get_logger(__name__)


def main() -> None:
    container = build_container()
    scheduler = build_scheduler(container)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    scheduler.start()
    log.info("worker_started", jobs=[job.id for job in scheduler.get_jobs()])
    stop.wait()
    scheduler.shutdown(wait=True)
    container.close()
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
