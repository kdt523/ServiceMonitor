"""
Host services router — manage individual services on a host (toggle, check-now, update interval).
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.models.host import Host
from app.models.host_service import HostService
from app.models.event_log import EventLog
from app.models.user import User

router = APIRouter(prefix="/hosts", tags=["host-services"])


# ── Toggle a service on/off ─────────────────────────────────────────────────
@router.post("/{host_id}/services/{service_id}/toggle")
async def toggle_service(
    host_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.scheduler import schedule_service, unschedule_service

    svc = await _get_service(db, service_id, host_id, current_user.id)
    svc.is_active = not svc.is_active

    if svc.is_active:
        schedule_service(svc.id, svc.interval_minutes)
        svc.status = "pending"
        event_type = "service_enabled"
    else:
        unschedule_service(svc.id)
        event_type = "service_disabled"

    db.add(EventLog(
        host_id=host_id,
        service_type=svc.service_type,
        event_type=event_type,
        message=f"{svc.service_type.upper()} service {'enabled' if svc.is_active else 'disabled'}",
    ))
    await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=302)


# ── Update service interval ─────────────────────────────────────────────────
@router.post("/{host_id}/services/{service_id}/interval")
async def update_interval(
    host_id: int,
    service_id: int,
    interval_minutes: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.scheduler import reschedule_service

    svc = await _get_service(db, service_id, host_id, current_user.id)
    svc.interval_minutes = max(1, interval_minutes)
    if svc.is_active:
        reschedule_service(svc.id, svc.interval_minutes)
    await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=302)


# ── Manual check-now ────────────────────────────────────────────────────────
@router.post("/{host_id}/services/{service_id}/check-now")
async def check_now(
    host_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.scheduler import run_check_now
    from app.services.health_checker import check_ssl

    svc = await _get_service(db, service_id, host_id, current_user.id)  # ownership check

    # For SSL, run a fresh check to get the rich cert details (not persisted to DB)
    ssl_cert_details = None
    if svc.service_type == "ssl":
        from app.models.host import Host as HostModel
        host_res = await db.execute(select(HostModel).where(HostModel.id == host_id))
        host_obj = host_res.scalar_one_or_none()
        if host_obj:
            fresh = await check_ssl(host_obj.url)
            ssl_cert_details = fresh.get("ssl_cert_details")

    await run_check_now(service_id)

    # Re-fetch updated service
    result = await db.execute(select(HostService).where(HostService.id == service_id))
    svc = result.scalar_one()
    return JSONResponse({
        "status": svc.status,
        "response_time_ms": svc.response_time_ms,
        "ssl_days_remaining": svc.ssl_days_remaining,
        "ssl_cert_details": ssl_cert_details,
        "last_checked_at": svc.last_checked_at.isoformat() if svc.last_checked_at else None,
        "error_message": svc.last_error if hasattr(svc, "last_error") else None,
    })


# ── Get service check history ───────────────────────────────────────────────
@router.get("/{host_id}/services/{service_id}/logs")
async def service_logs(
    host_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import desc
    from app.models.check_log import CheckLog

    await _get_service(db, service_id, host_id, current_user.id)
    result = await db.execute(
        select(CheckLog)
        .where(CheckLog.service_id == service_id)
        .order_by(desc(CheckLog.checked_at))
        .limit(100)
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "status": l.status,
            "response_time_ms": l.response_time_ms,
            "ssl_days_remaining": l.ssl_days_remaining,
            "error_message": l.error_message,
            "checked_at": l.checked_at.isoformat(),
        }
        for l in logs
    ]


# ── Helper ──────────────────────────────────────────────────────────────────
async def _get_service(
    db: AsyncSession, service_id: int, host_id: int, user_id: int
) -> HostService:
    # Verify host ownership first
    host_result = await db.execute(
        select(Host).where(Host.id == host_id, Host.user_id == user_id)
    )
    if host_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Host not found")

    svc_result = await db.execute(
        select(HostService).where(
            HostService.id == service_id,
            HostService.host_id == host_id,
        )
    )
    svc = svc_result.scalar_one_or_none()
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return svc


# ── Update service config (port, keyword, headers) ──────────────────────────
@router.post("/{host_id}/services/{service_id}/config")
async def update_service_config(
    host_id: int,
    service_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = await _get_service(db, service_id, host_id, current_user.id)
    body = await request.json()

    if "port" in body:
        svc.port = int(body["port"]) if body["port"] else None

    if "keyword_check" in body:
        svc.keyword_check = body["keyword_check"] or None

    if "custom_headers" in body:
        headers = body["custom_headers"]
        # Accept dict or None
        if isinstance(headers, dict) and headers:
            svc.custom_headers = headers
        else:
            svc.custom_headers = None

    await db.commit()
    return JSONResponse({"ok": True})
