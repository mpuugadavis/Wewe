"""Bounded, durable product-media orphan cleanup worker."""
from __future__ import annotations
import logging, signal, time
from app.config import get_settings
from app.db import SessionLocal
from app.services.media_lifecycle import collect_orphaned_product_media
from app.services.media_uploads import build_media_storage
from app.services.worker_health import mark_failure, mark_started, mark_success

logger=logging.getLogger("wewe.media_cleanup_worker")
_shutdown=False
WORKER_NAME="media_cleanup"

def _request_shutdown(_signum:int,_frame:object)->None:
    global _shutdown
    _shutdown=True

def run()->None:
    settings=get_settings()
    logging.basicConfig(level=settings.log_level,format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM,_request_shutdown); signal.signal(signal.SIGINT,_request_shutdown)
    if settings.storage_provider=="DISABLED":
        logger.warning("Media cleanup worker disabled because STORAGE_PROVIDER=DISABLED"); return
    storage=build_media_storage(settings)
    if storage is None: return
    with SessionLocal() as db: mark_started(db,WORKER_NAME)
    logger.info("Media cleanup worker started")
    while not _shutdown:
        started=time.monotonic()
        try:
            with SessionLocal() as db:
                result=collect_orphaned_product_media(db,storage,grace_period_seconds=settings.media_cleanup_grace_seconds,dry_run=settings.media_cleanup_dry_run,prefix=settings.media_cleanup_prefix)
                duration_ms=round((time.monotonic()-started)*1000)
                mark_success(db,WORKER_NAME,duration_ms=duration_ms,scanned=result.scanned,candidates=result.candidates,deleted=result.deleted,failed=result.failed)
                logger.info("Media cleanup cycle completed",extra={"scanned":result.scanned,"candidates":result.candidates,"deleted":result.deleted,"failed":result.failed,"dry_run":settings.media_cleanup_dry_run})
        except Exception as exc:
            duration_ms=round((time.monotonic()-started)*1000)
            logger.exception("Media cleanup cycle failed")
            with SessionLocal() as db: mark_failure(db,WORKER_NAME,duration_ms=duration_ms,error=str(exc))
        if not _shutdown: time.sleep(settings.media_cleanup_poll_seconds)
    logger.info("Media cleanup worker stopped")

if __name__=="__main__": run()
