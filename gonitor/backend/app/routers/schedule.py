"""
Schedule router — shows all active scheduled jobs.
"""
from datetime import timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.host import Host
from app.models.host_service import HostService
from app.models.user import User

router = APIRouter(tags=["schedule"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule_data = await _build_schedule(db, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="schedule/index.html",
        context={"user": current_user, "schedule_items": schedule_data},
    )


@router.get("/api/schedule")
async def api_schedule(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """JSON endpoint for live schedule updates."""
    data = await _build_schedule(db, current_user.id)
    return JSONResponse(data)


async def _build_schedule(db: AsyncSession, user_id: int) -> list[dict]:
    from app.services.scheduler import scheduler, _job_id

    result = await db.execute(
        select(HostService, Host)
        .join(Host, Host.id == HostService.host_id)
        .where(Host.user_id == user_id, HostService.is_active == True)  # noqa
        .order_by(Host.name, HostService.service_type)
    )
    rows = result.fetchall()

    items = []
    for svc, host in rows:
        jid = _job_id(svc.id)
        job = scheduler.get_job(jid)
        items.append({
            "service_id": svc.id,
            "host_id": host.id,
            "host_name": host.name,
            "service_type": svc.service_type,
            "interval_minutes": svc.interval_minutes,
            "schedule_expr": f"Every {svc.interval_minutes} min",
            "last_run": svc.last_checked_at.isoformat() + "Z" if svc.last_checked_at else None,
            "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
            "status": svc.status,
        })
    return items
