"""Continuous notification outbox worker.

Runs separately from the API so durable notifications continue processing when
API request traffic is idle. Multiple worker replicas are safe because the
outbox claim operation uses PostgreSQL row locking with SKIP LOCKED.
"""

from __future__ import annotations

import logging
import signal
import time

from app.config import get_settings
from app.db import SessionLocal
from app.services.notification_outbox import process_outbox_batch

logger = logging.getLogger("wewe.notification_worker")
_shutdown = False


def _request_shutdown(_signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True


def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    logger.info("Notification worker started")
    while not _shutdown:
        try:
            processed = process_outbox_batch(
                SessionLocal,
                batch_size=settings.notification_worker_batch_size,
                stale_after_seconds=settings.notification_worker_stale_after_seconds,
                max_attempts=settings.notification_worker_max_attempts,
            )
            if processed:
                logger.info("Notification batch processed", extra={"processed": processed})
            else:
                time.sleep(settings.notification_worker_poll_seconds)
        except Exception:
            logger.exception("Notification worker batch failed")
            time.sleep(settings.notification_worker_poll_seconds)

    logger.info("Notification worker stopped")


if __name__ == "__main__":
    run()
