def test_worker_health_lifecycle(db_session):
    from app.services.worker_health import mark_failure, mark_heartbeat, mark_started, mark_success, worker_snapshot
    mark_started(db_session,"media_cleanup")
    assert worker_snapshot(db_session,"media_cleanup")["status"]=="RUNNING"
    mark_heartbeat(db_session,"media_cleanup")
    mark_success(db_session,"media_cleanup",duration_ms=42,scanned=10,candidates=2,deleted=2)
    snapshot=worker_snapshot(db_session,"media_cleanup")
    assert snapshot["status"]=="HEALTHY" and snapshot["last_deleted"]==2
    mark_failure(db_session,"media_cleanup",duration_ms=7,error="storage unavailable")
    snapshot=worker_snapshot(db_session,"media_cleanup")
    assert snapshot["status"]=="FAILING" and snapshot["last_error"]=="storage unavailable"
