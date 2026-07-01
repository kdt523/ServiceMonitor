"""
Public router — unauthenticated endpoints.

GET /status — Public status page showing all active hosts and their service statuses.
No login required. Designed to be shared with external users/customers.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.models.host import Host
from app.models.host_service import HostService

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/status", response_class=HTMLResponse)
async def public_status_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public status page — no authentication required."""
    # Load all active hosts with their services
    result = await db.execute(
        select(Host)
        .where(Host.is_active == True)  # noqa: E712
        .options(selectinload(Host.services))
        .order_by(Host.name)
    )
    hosts = result.scalars().all()

    # Determine overall status
    all_services = []
    for host in hosts:
        all_services.extend([s for s in host.services if s.is_active])

    if not all_services:
        overall = "no_data"
    elif all(s.status == "healthy" for s in all_services):
        overall = "operational"
    elif any(s.status == "problem" for s in all_services):
        overall = "outage"
    else:
        overall = "degraded"

    return templates.TemplateResponse(
        request=request,
        name="status.html",
        context={
            "hosts": hosts,
            "overall_status": overall,
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )
