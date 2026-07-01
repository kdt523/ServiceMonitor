"""
SMS notification service using Twilio REST API (via httpx).

Sends alerts on: problem, warning, recovery (healthy).
Requires TWILIO_SID and TWILIO_AUTH_TOKEN to be configured.
"""
import logging
import httpx

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


async def send_sms(to_phone: str, body: str, raise_on_error: bool = False) -> bool:
    """Send an SMS via Twilio REST API. Returns True on success."""
    try:
        s = await _load_settings()

        if not s.twilio_sid or not s.twilio_auth_token or not s.twilio_from_phone:
            logger.debug("Twilio not configured — skipping SMS")
            if raise_on_error:
                missing = []
                if not s.twilio_sid:
                    missing.append("Account SID")
                if not s.twilio_auth_token:
                    missing.append("Auth Token")
                if not s.twilio_from_phone:
                    missing.append("From Phone")
                raise ValueError(f"Twilio configuration error: missing {', '.join(missing)}.")
            return False

        url = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_sid}/Messages.json"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data={"From": s.twilio_from_phone, "To": to_phone, "Body": body},
                auth=(s.twilio_sid, s.twilio_auth_token),
                timeout=15.0,
            )
        if resp.status_code in (200, 201):
            logger.info("SMS sent to %s", to_phone)
            return True
        else:
            logger.warning("Twilio returned %d: %s", resp.status_code, resp.text)
            if raise_on_error:
                raise ValueError(f"Twilio error {resp.status_code}: {resp.text}")
            return False
    except Exception as exc:
        logger.warning("send_sms failed: %s", exc)
        if raise_on_error:
            raise exc
        return False


async def send_status_sms(
    host_name: str,
    service_type: str,
    old_status: str,
    new_status: str,
) -> None:
    s = await _load_settings()
    if not s.notify_via_sms or not s.recipient_phone:
        return
    emoji = {"healthy": "✅", "warning": "⚠️", "problem": "🔴"}.get(new_status, "ℹ️")
    body = (
        f"{emoji} Gonitor Alert\n"
        f"Host: {host_name}\n"
        f"Service: {service_type.upper()}\n"
        f"Status: {new_status.upper()} (was {old_status.upper()})"
    )
    await send_sms(s.recipient_phone, body)
