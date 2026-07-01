"""
Notification dispatcher.

Rules:
- Only fires when status actually changes (caller's responsibility)
- Skips pending → anything transitions
- Routes to email, SMS, and/or webhook based on AppSettings
"""
import logging

logger = logging.getLogger(__name__)

# Statuses that should trigger notifications
NOTIFIABLE_STATUSES = {"healthy", "warning", "problem"}


async def send_notifications(host, service, old_status: str, new_status: str) -> None:
    """
    Dispatch email, SMS, and webhook notifications for a status change.

    Args:
        host:       Host ORM instance
        service:    HostService ORM instance
        old_status: Previous status string
        new_status: New status string
    """
    # Skip pending → anything (first check, no prior baseline)
    if old_status == "pending":
        return

    # Only notify on meaningful final statuses
    if new_status not in NOTIFIABLE_STATUSES:
        return

    try:
        from app.services.mail_service import send_status_email
        from app.services.sms_service import send_status_sms
        from app.services.webhook_service import send_webhook

        host_name = host.name
        service_type = service.service_type
        error_msg = service.last_error

        # Load webhook settings
        webhook_url = None
        try:
            from app.database import AsyncSessionFactory
            from sqlalchemy import select
            from app.models.app_settings import AppSettings
            async with AsyncSessionFactory() as session:
                result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
                settings = result.scalar_one_or_none()
                if settings and settings.webhook_enabled and settings.webhook_url:
                    webhook_url = settings.webhook_url
        except Exception as we:
            logger.warning("Failed to load webhook settings: %s", we)

        # Fire all concurrently
        import asyncio
        tasks = [
            send_status_email(host_name, service_type, old_status, new_status),
            send_status_sms(host_name, service_type, old_status, new_status),
        ]

        if webhook_url:
            tasks.append(
                send_webhook(
                    webhook_url=webhook_url,
                    host_name=host_name,
                    service_type=service_type,
                    status=new_status,
                    error=error_msg,
                )
            )

        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.warning("send_notifications failed: %s", exc)
