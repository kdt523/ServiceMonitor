"""
Hosts router — CRUD for monitored hosts.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.host import Host
from app.models.host_service import HostService, SERVICE_TYPES
from app.models.event_log import EventLog
from app.models.user import User

router = APIRouter(prefix="/hosts", tags=["hosts"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ── List all hosts ──────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def list_hosts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Host)
        .where(Host.user_id == current_user.id)
        .options(selectinload(Host.services))
        .order_by(Host.name)
    )
    hosts = result.scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="hosts/index.html",
        context={"user": current_user, "hosts": hosts},
    )


# ── Add host — GET ──────────────────────────────────────────────────────────
@router.get("/add", response_class=HTMLResponse)
async def add_host_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="hosts/add.html",
        context={"user": current_user, "error": None},
    )


# ── Add host — POST ─────────────────────────────────────────────────────────
@router.post("/add")
async def add_host(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    canonical_name: Optional[str] = Form(None),
    ipv4: Optional[str] = Form(None),
    ipv6: Optional[str] = Form(None),
    os: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    enable_http: Optional[str] = Form(None),
    enable_https: Optional[str] = Form(None),
    enable_ssl: Optional[str] = Form(None),
    enable_tcp: Optional[str] = Form(None),
    enable_ping: Optional[str] = Form(None),
    enable_dns: Optional[str] = Form(None),
    enable_ssh: Optional[str] = Form(None),
    enable_ftp: Optional[str] = Form(None),
    enable_smtp: Optional[str] = Form(None),
    interval_minutes: int = Form(5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = Host(
        user_id=current_user.id,
        name=name.strip(),
        url=url.strip(),
        canonical_name=canonical_name or None,
        ipv4=ipv4 or None,
        ipv6=ipv6 or None,
        os=os or None,
        location=location or None,
        is_active=True,
    )
    db.add(host)
    await db.flush()  # get host.id

    # Create service rows for each type (all 9)
    for stype, checked in [
        ("http", enable_http),
        ("https", enable_https),
        ("ssl", enable_ssl),
        ("tcp", enable_tcp),
        ("ping", enable_ping),
        ("dns", enable_dns),
        ("ssh", enable_ssh),
        ("ftp", enable_ftp),
        ("smtp", enable_smtp),
    ]:
        svc = HostService(
            host_id=host.id,
            service_type=stype,
            is_active=bool(checked),
            interval_minutes=interval_minutes,
        )
        db.add(svc)

    # Log event
    db.add(EventLog(
        host_id=host.id,
        event_type="host_added",
        message=f"Host '{name}' added",
    ))

    await db.commit()

    # Schedule active services
    from app.services.scheduler import schedule_service
    result = await db.execute(
        select(HostService).where(HostService.host_id == host.id, HostService.is_active == True)  # noqa
    )
    for svc in result.scalars().all():
        schedule_service(svc.id, svc.interval_minutes)

    return RedirectResponse(url=f"/hosts/{host.id}", status_code=302)


# ── Host detail ─────────────────────────────────────────────────────────────
@router.get("/{host_id}", response_class=HTMLResponse)
async def host_detail(
    host_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = await _get_host(db, host_id, current_user.id)
    result = await db.execute(
        select(HostService).where(HostService.host_id == host_id).order_by(HostService.service_type)
    )
    services = result.scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="hosts/detail.html",
        context={"user": current_user, "host": host, "services": services},
    )


# ── Edit host — GET ─────────────────────────────────────────────────────────
@router.get("/{host_id}/edit", response_class=HTMLResponse)
async def edit_host_page(
    host_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = await _get_host(db, host_id, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="hosts/edit.html",
        context={"user": current_user, "host": host, "error": None},
    )


# ── Edit host — POST ────────────────────────────────────────────────────────
@router.post("/{host_id}/edit")
async def edit_host(
    host_id: int,
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    canonical_name: Optional[str] = Form(None),
    ipv4: Optional[str] = Form(None),
    ipv6: Optional[str] = Form(None),
    os: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = await _get_host(db, host_id, current_user.id)
    host.name = name.strip()
    host.url = url.strip()
    host.canonical_name = canonical_name or None
    host.ipv4 = ipv4 or None
    host.ipv6 = ipv6 or None
    host.os = os or None
    host.location = location or None
    host.is_active = bool(is_active)

    db.add(EventLog(host_id=host_id, event_type="host_updated", message=f"Host '{name}' updated"))
    await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=302)


# ── Delete host ─────────────────────────────────────────────────────────────
@router.post("/{host_id}/delete")
async def delete_host(
    host_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = await _get_host(db, host_id, current_user.id)

    # Unschedule all services
    from app.services.scheduler import unschedule_service
    svc_result = await db.execute(select(HostService).where(HostService.host_id == host_id))
    for svc in svc_result.scalars().all():
        unschedule_service(svc.id)

    await db.delete(host)
    await db.commit()
    return RedirectResponse(url="/hosts", status_code=302)


# ── Toggle host active ──────────────────────────────────────────────────────
@router.post("/{host_id}/toggle")
async def toggle_host(
    host_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.scheduler import schedule_service, unschedule_service
    host = await _get_host(db, host_id, current_user.id)
    host.is_active = not host.is_active

    svc_result = await db.execute(select(HostService).where(HostService.host_id == host_id))
    for svc in svc_result.scalars().all():
        if host.is_active and svc.is_active:
            schedule_service(svc.id, svc.interval_minutes)
        else:
            unschedule_service(svc.id)

    await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=302)


# ── Helper ──────────────────────────────────────────────────────────────────
async def _get_host(db: AsyncSession, host_id: int, user_id: int) -> Host:
    result = await db.execute(
        select(Host).where(Host.id == host_id, Host.user_id == user_id)
    )
    host = result.scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    return host
