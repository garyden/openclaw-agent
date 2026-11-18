import os
import smtplib
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str) -> None:
    recipient = (to or "").strip()
    if not recipient:
        raise ValueError("Email recipient is required.")

    host = os.getenv("EMAIL_HOST", "").strip()
    port_text = os.getenv("EMAIL_PORT", "").strip()
    user = os.getenv("EMAIL_USER", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "")

    if not host:
        raise ValueError("EMAIL_HOST is not set.")
    if not port_text:
        raise ValueError("EMAIL_PORT is not set.")
    if not user:
        raise ValueError("EMAIL_USER is not set.")
    if not password:
        raise ValueError("EMAIL_PASSWORD is not set.")

    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("EMAIL_PORT must be an integer.") from exc

    message = EmailMessage()
    message["From"] = user
    message["To"] = recipient
    message["Subject"] = subject or ""
    message.set_content(body or "")

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)
