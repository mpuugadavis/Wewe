import importlib.util
from pathlib import Path


def test_render_hostname_and_neon_driver_configuration():
    source = Path(__file__).resolve().parents[2] / "deploy" / "start.py"
    spec = importlib.util.spec_from_file_location("free_start", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = {"RENDER_EXTERNAL_HOSTNAME":"wewe-test.onrender.com", "DATABASE_URL":"postgresql://user:pass@db.neon.tech/wewe?sslmode=require"}
    module.configure_environment(env)
    assert env["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert env["TRUSTED_HOSTS"] == "wewe-test.onrender.com,localhost,127.0.0.1"
    assert env["PAWAPAY_DEPOSIT_CALLBACK_URL"] == "https://wewe-test.onrender.com/api/v1/payments/pawapay/deposit-callback"
    env["CORS_ORIGINS"] = "https://custom.example"
    module.configure_environment(env)
    assert env["CORS_ORIGINS"] == "https://custom.example"


def test_neon_urls_use_existing_psycopg_driver():
    from app.config import Settings
    settings = Settings(app_env="test", secret_key="test-only-secret-key-with-more-than-32-characters",
                        database_url="postgresql://user:pass@ep-example-pooler.neon.tech/neondb?sslmode=require",
                        database_url_unpooled="postgresql://user:pass@ep-example.neon.tech/neondb?sslmode=require")
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "-pooler" in settings.database_url
    assert "-pooler" not in settings.database_url_unpooled
    assert settings.database_url_unpooled.startswith("postgresql+psycopg://")
