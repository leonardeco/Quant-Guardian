"""Password-reset mail. No-op unless SMTP_HOST is set."""
import asyncio
import smtplib
from email.message import EmailMessage

from .config import settings


def reset_link(token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/restablecer?token={token}"


async def send_reset_email(to: str, token: str) -> bool:
    if not settings.smtp_host:
        return False
    link = reset_link(token)
    msg = EmailMessage()
    msg["Subject"] = "Restablecer contraseña"
    msg["From"] = settings.smtp_from or settings.smtp_user or "noreply@localhost"
    msg["To"] = to
    msg.set_content(
        "Para restablecer su contraseña abra este enlace en los próximos 30 minutos:\n\n"
        f"{link}\n"
    )

    def _send() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)

    try:
        await asyncio.to_thread(_send)
        return True
    except Exception:
        print("reset email failed")
        return False
