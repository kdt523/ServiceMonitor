"""
Webhook notification service — sends Slack-compatible JSON payloads.

Triggered on status changes alongside email and SMS.
Uses httpx (already in requirements) for async HTTP POST.
"""
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Color map for Slack attachment sidebar
STATUS_COLORS = {
    "healthy": "#1D9E75",
    "warning": "#EF9F27",
    "problem": "#E24B4A",
}

STATUS_EMOJI = {
    "healthy": "✅",
    "warning": "⚠️",
    "problem": "🔴",
}


async def send_webhook(
    webhook_url: str,
    host_name: str,
    service_type: str,
    status: str,
    error: str | None,
    checked_at: str | None = None,
) -> bool:
    """
    POST a Slack-compatible JSON payload to the webhook URL.

    Returns True on success, False on failure. Never raises.
    """
    if not webhook_url:
        return False

    color = STATUS_COLORS.get(status, "#888780")
    emoji = STATUS_EMOJI.get(status, "")
    ts = checked_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "text": f"*[{status.upper()}]* {emoji} {host_name} {service_type.upper()}",
        "attachments": [
            {
                "color": color,
                "fields": [
                    {"title": "Host", "value": host_name, "short": True},
                    {"title": "Service", "value": service_type.upper(), "short": True},
                    {"title": "Status", "value": status.upper(), "short": True},
                    {"title": "Error", "value": error or "None", "short": True},
                    {"title": "Checked at", "value": ts, "short": True},
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning("Webhook returned HTTP %d for %s", resp.status_code, webhook_url)
                return False
            return True
    except Exception as exc:
        logger.error("Webhook failed for %s: %s", webhook_url, exc)
        return False


async def send_test_webhook(webhook_url: str) -> bool:
    """Send a test payload to verify webhook configuration."""
    return await send_webhook(
        webhook_url=webhook_url,
        host_name="Test Host",
        service_type="https",
        status="healthy",
        error=None,
        checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
