"""
Settings router — view and save application-wide settings.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.app_settings import AppSettings
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def _get_or_create_settings(db: AsyncSession) -> AppSettings:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app_settings = await _get_or_create_settings(db)
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={"user": current_user, "settings": app_settings, "saved": False},
    )


@router.post("", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    site_url: Optional[str] = Form(None),
    site_name: Optional[str] = Form(None),
    smtp_host: Optional[str] = Form(None),
    smtp_port: int = Form(587),
    smtp_user: Optional[str] = Form(None),
    smtp_password: Optional[str] = Form(None),
    smtp_from_name: Optional[str] = Form(None),
    smtp_from_email: Optional[str] = Form(None),
    smtp_use_tls: Optional[str] = Form(None),
    notify_via_email: Optional[str] = Form(None),
    notify_via_sms: Optional[str] = Form(None),
    recipient_name: Optional[str] = Form(None),
    recipient_email: Optional[str] = Form(None),
    recipient_phone: Optional[str] = Form(None),
    twilio_sid: Optional[str] = Form(None),
    twilio_auth_token: Optional[str] = Form(None),
    twilio_from_phone: Optional[str] = Form(None),
    webhook_url: Optional[str] = Form(None),
    webhook_enabled: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = await _get_or_create_settings(db)
    s.site_url = site_url or None
    s.site_name = site_name or "ServiceMonitor"
    s.smtp_host = smtp_host or None
    s.smtp_port = smtp_port
    s.smtp_user = smtp_user or None
    # Keep existing password if blank
    if smtp_password and smtp_password.strip():
        s.smtp_password = smtp_password.strip()
    s.smtp_from_name = smtp_from_name or None
    s.smtp_from_email = smtp_from_email or None
    s.smtp_use_tls = bool(smtp_use_tls)
    s.notify_via_email = bool(notify_via_email)
    s.notify_via_sms = bool(notify_via_sms)
    s.recipient_name = recipient_name or None
    s.recipient_email = recipient_email or None
    s.recipient_phone = recipient_phone or None
    s.twilio_sid = twilio_sid or None
    if twilio_auth_token and twilio_auth_token.strip():
        s.twilio_auth_token = twilio_auth_token.strip()
    s.twilio_from_phone = twilio_from_phone or None
    s.webhook_url = webhook_url or None
    s.webhook_enabled = bool(webhook_enabled)
    await db.commit()
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={"user": current_user, "settings": s, "saved": True},
    )


@router.post("/monitoring/toggle")
async def toggle_monitoring(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.scheduler import set_monitoring_enabled, is_monitoring_enabled
    from app.services.ws_manager import broadcast_monitoring_toggled

    s = await _get_or_create_settings(db)
    new_state = not s.monitoring_enabled
    s.monitoring_enabled = new_state
    await db.commit()

    set_monitoring_enabled(new_state)
    broadcast_monitoring_toggled(new_state)
    return JSONResponse({"monitoring_enabled": new_state})


@router.post("/test-email")
async def test_email(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.mail_service import send_email
    s = await _get_or_create_settings(db)
    try:
        ok = await send_email(
            to_email=s.recipient_email or current_user.email,
            to_name=s.recipient_name or current_user.full_name,
            subject="ServiceMonitor — Test Email",
            body_html="<p>This is a test email from <strong>ServiceMonitor</strong>.</p>",
            body_text="This is a test email from ServiceMonitor.",
            raise_on_error=True,
        )
        return JSONResponse({"success": ok})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)})


@router.post("/test-sms")
async def test_sms(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.sms_service import send_sms
    s = await _get_or_create_settings(db)
    try:
        ok = await send_sms(
            to_phone=s.recipient_phone or "",
            body="ServiceMonitor test SMS — your alerts are working!",
            raise_on_error=True,
        )
        return JSONResponse({"success": ok})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)})


@router.post("/test-webhook")
async def test_webhook(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.webhook_service import send_test_webhook
    s = await _get_or_create_settings(db)
    if not s.webhook_url:
        return JSONResponse({"success": False, "error": "No webhook URL configured"})
    try:
        ok = await send_test_webhook(s.webhook_url)
        return JSONResponse({"success": ok, "error": None if ok else "Webhook returned non-200"})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)})
