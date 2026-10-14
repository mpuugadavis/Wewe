import json
from email.utils import parseaddr
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings


def send_email(to_address: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_transport == "BREVO_API":
        if not settings.brevo_api_key:
            raise RuntimeError("Brevo API email is not configured")
        name, address = parseaddr(settings.email_from)
        payload = {"sender": {"email": address, "name": name or "WEWE"},
                   "to": [{"email": to_address}], "subject": subject, "textContent": body}
        request = Request("https://api.brevo.com/v3/smtp/email",
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"api-key": settings.brevo_api_key.get_secret_value(),
                                   "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                if response.status != 201:
                    raise RuntimeError("Brevo did not accept the email")
        except HTTPError as exc:
            # Do not persist provider bodies, recipient addresses or API credentials in logs.
            raise RuntimeError(f"Brevo email request failed (HTTP {exc.code})") from None
        except URLError:
            raise RuntimeError("Brevo email service is temporarily unavailable") from None
        return
    if not settings.smtp_host:
        return
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls(context=context)
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        server.send_message(message)
