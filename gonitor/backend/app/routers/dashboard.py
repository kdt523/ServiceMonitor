"""
Dashboard router — main overview page with counters for all service statuses.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.host import Host
from app.models.host_service import HostService
from app.models.user import User

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Load all hosts with their services
    result = await db.execute(
        select(Host)
        .where(Host.user_id == current_user.id)
        .options(selectinload(Host.services))
        .order_by(Host.name)
    )
    hosts = result.scalars().all()

    # Aggregate status counts across all active services
    counts_result = await db.execute(
        select(HostService.status, func.count(HostService.id))
        .join(Host, Host.id == HostService.host_id)
        .where(Host.user_id == current_user.id, HostService.is_active == True)  # noqa
        .group_by(HostService.status)
    )
    counts = {row[0]: row[1] for row in counts_result.fetchall()}

    # Build per-host service map: {host_id: {service_type: service_obj}}
    host_service_map = {}
    for host in hosts:
        host_service_map[host.id] = {svc.service_type: svc for svc in host.services}

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": current_user,
            "hosts": hosts,
            "host_service_map": host_service_map,
            "healthy_count": counts.get("healthy", 0),
            "warning_count": counts.get("warning", 0),
            "problem_count": counts.get("problem", 0),
            "pending_count": counts.get("pending", 0),
            "total_hosts": len(hosts),
        },
    )
