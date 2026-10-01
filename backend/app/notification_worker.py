"""Process the durable notification outbox.

Examples:
    python -m app.notification_worker --once
    python -m app.notification_worker --interval 5
"""

from __future__ import annotations

import argparse
import logging
import time

from app.config import get_settings
from app.db import SessionLocal
from app.observability import configure_logging
from app.services.notification_outbox import process_outbox_batch


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("wewe.notification_worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process the WEWE notification outbox")
    parser.add_argument("--once", action="store_true", help="Process one bounded batch and exit")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")
    parser.add_argument("--stale-after", type=int, default=300, help="Seconds before a PROCESSING job is reclaimable")
    parser.add_argument("--max-attempts", type=int, default=8)
    args = parser.parse_args()

    if args.batch_size < 1 or args.interval <= 0 or args.stale_after < 1 or args.max_attempts < 1:
        parser.error("batch-size, interval, stale-after, and max-attempts must be positive")

    while True:
        try:
            processed = process_outbox_batch(
                SessionLocal,
                batch_size=args.batch_size,
                stale_after_seconds=args.stale_after,
                max_attempts=args.max_attempts,
            )
            if processed:
                logger.info("Processed %d notification outbox job(s)", processed)
        except Exception:
            logger.exception("Notification outbox polling cycle failed")

        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
