from app.workers import notification_worker


def test_worker_processes_until_shutdown(database, monkeypatch):
    calls = []

    class Settings:
        log_level = "INFO"
        notification_worker_batch_size = 10
        notification_worker_stale_after_seconds = 300
        notification_worker_max_attempts = 8
        notification_worker_poll_seconds = 0.001

    def fake_settings():
        return Settings()

    def fake_process(*args, **kwargs):
        calls.append((args, kwargs))
        notification_worker._shutdown = True
        return 1

    monkeypatch.setattr(notification_worker, "get_settings", fake_settings)
    monkeypatch.setattr(notification_worker, "process_outbox_batch", fake_process)
    monkeypatch.setattr(notification_worker, "SessionLocal", lambda: database)
    monkeypatch.setattr(notification_worker, "_shutdown", False)

    notification_worker.run()

    assert len(calls) == 1
    assert calls[0][1]["batch_size"] == 10
    assert calls[0][1]["stale_after_seconds"] == 300
    assert calls[0][1]["max_attempts"] == 8
