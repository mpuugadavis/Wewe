from app.workers import media_cleanup_worker

def test_media_cleanup_worker_returns_cleanly_when_storage_disabled(monkeypatch):
    class Settings:
        storage_provider="DISABLED"
        log_level="INFO"
    monkeypatch.setattr(media_cleanup_worker,"get_settings",lambda:Settings())
    monkeypatch.setattr(media_cleanup_worker,"_shutdown",False)
    media_cleanup_worker.run()
