"""
Email notification service using aiosmtplib.

Sends alerts on:
  - Service goes to 'problem'
  - Service recovers to 'healthy'

Requires SMTP settings to be configured (smtp_host must be non-empty).
"""
import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


async def _load_settings():
    """
    Load AppSettings from the database if available.
    Fallback to environment/config settings otherwise.
    """
    from app.config import get_settings
    try:
        from app.database import AsyncSessionFactory
        from sqlalchemy import select
        from app.models.app_settings import AppSettings

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
            db_settings = result.scalar_one_or_none()
            if db_settings:
                return db_settings
    except Exception as exc:
        logger.warning("Failed to load AppSettings from DB, falling back to config: %s", exc)
    return get_settings()


async def send_email(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
    raise_on_error: bool = False,
) -> bool:
    """
    Send an email via aiosmtplib.
    Returns True on success, False on failure.
    """
    try:
        import aiosmtplib
        s = await _load_settings()
        
        from_email = s.smtp_from_email or s.smtp_user

        if not s.smtp_host or not from_email:
            logger.debug("SMTP not configured — skipping email")
            if raise_on_error:
                missing = []
                if not s.smtp_host:
                    missing.append("SMTP Host")
                if not from_email:
                    missing.append("From Email (or Username)")
                raise ValueError(f"SMTP configuration error: missing {', '.join(missing)}.")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{s.smtp_from_name} <{from_email}>" if s.smtp_from_name else from_email
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email

        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        use_tls = (s.smtp_port == 465)
        start_tls = (s.smtp_port == 587) or s.smtp_use_tls

        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            use_tls=use_tls,
            start_tls=start_tls,
        )
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.warning("send_email failed: %s", exc)
        if raise_on_error:
            raise exc
        return False


def _build_status_email(
    host_name: str,
    service_type: str,
    old_status: str,
    new_status: str,
    site_url: str,
) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    emoji = {"healthy": "✅", "warning": "⚠️", "problem": "🔴", "pending": "⏳"}
    icon = emoji.get(new_status, "ℹ️")
    subject = f"{icon} [{new_status.upper()}] {host_name} — {service_type.upper()} service"

    html = f"""
    <html><body style="font-family:sans-serif;background:#0d1117;color:#e6edf3;padding:20px">
    <div style="max-width:520px;margin:auto;background:#161b22;border-radius:10px;padding:24px">
      <h2 style="color:#388bfd;margin-top:0">{icon} ServiceMonitor Alert</h2>
      <p><strong>Host:</strong> {host_name}</p>
      <p><strong>Service:</strong> {service_type.upper()}</p>
      <p><strong>Status:</strong> <span style="color:{'#3fb950' if new_status=='healthy' else '#f85149'}">{new_status.upper()}</span></p>
      <p><strong>Previous:</strong> {old_status.upper()}</p>
      <hr style="border-color:#30363d"/>
      <a href="{site_url}/hosts" style="color:#388bfd">View Dashboard →</a>
    </div>
    </body></html>
    """
    text = f"[{new_status.upper()}] {host_name} / {service_type}: was {old_status}"
    return subject, html, text


async def send_status_email(
    host_name: str,
    service_type: str,
    old_status: str,
    new_status: str,
) -> None:
    s = await _load_settings()
    if not s.notify_via_email or not s.recipient_email:
        return
    subject, html, text = _build_status_email(
        host_name, service_type, old_status, new_status, s.site_url
    )
    await send_email(
        to_email=s.recipient_email,
        to_name=s.recipient_name,
        subject=subject,
        body_html=html,
        body_text=text,
    )
