import json
from types import SimpleNamespace
from urllib.error import HTTPError
import pytest
from pydantic import SecretStr
from app.services import mailer
from app.services.notification_outbox import _email_handler
from app.models import NotificationOutbox


def settings():
    return SimpleNamespace(email_transport="BREVO_API", brevo_api_key=SecretStr("private-test-key"), email_from="WEWE <sender@example.test>", smtp_host=None)


def test_brevo_uses_https_and_accepts_only_provider_success(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", settings)
    requests = []
    class Response:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def send(request, timeout):
        requests.append(request)
        assert timeout == 15
        return Response()
    monkeypatch.setattr(mailer, "urlopen", send)
    monkeypatch.setattr("app.services.notification_outbox.get_settings", settings)
    _email_handler(NotificationOutbox(payload={"to":"customer@example.test", "subject":"Delivery code", "body":"Code 12345678"}))
    request = requests[0]
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    body = json.loads(request.data)
    assert body["textContent"] == "Code 12345678"
    assert body["sender"]["email"] == "sender@example.test"
    assert request.get_header("Api-key") == "private-test-key"


def test_brevo_failure_is_retryable_without_exposing_provider_body(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", settings)
    def fail(*args, **kwargs):
        raise HTTPError("https://api.brevo.com", 429, "private provider detail", {}, None)
    monkeypatch.setattr(mailer, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 429") as error:
        mailer.send_email("customer@example.test", "Test", "Body")
    assert "private" not in str(error.value)
