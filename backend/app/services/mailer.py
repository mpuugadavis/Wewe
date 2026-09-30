import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings


def send_email(to_address: str, subject: str, body: str) -> None:
    settings = get_settings()
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
