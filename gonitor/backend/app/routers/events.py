"""
Events log router — view the persistent event/audit log.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.event_log import EventLog
from app.models.host import Host
from app.models.user import User

router = APIRouter(tags=["events"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/events", response_class=HTMLResponse)
async def events_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only show events for hosts owned by this user
    result = await db.execute(
        select(EventLog)
        .options(selectinload(EventLog.host))
        .join(Host, Host.id == EventLog.host_id, isouter=True)
        .where(
            (EventLog.host_id == None) |  # noqa
            (Host.user_id == current_user.id)
        )
        .order_by(desc(EventLog.created_at))
        .limit(200)
    )
    events = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="events/index.html",
        context={"user": current_user, "events": events},
    )
