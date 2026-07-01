from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_db
from app.dependencies import get_current_user
from app.models.resource import Resource
from app.models.check_log import CheckLog
from app.models.user import User
from app.schemas.resource import ResourceCreate, ResourceUpdate, ResourceRead
from app.schemas.check_log import CheckLogRead
from app.services.scheduler import schedule_resource, unschedule_resource, reschedule_resource
from app.services.health_checker import run_health_check
from app.services import scheduler as scheduler_module
from datetime import datetime, timezone

router = APIRouter(prefix="/resources", tags=["resources"])


# ---------------------------------------------------------------------------
# GET /resources — list all for current user
# ---------------------------------------------------------------------------
@router.get("", response_model=List[ResourceRead])
async def list_resources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resource).where(Resource.user_id == current_user.id)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# POST /resources — create new resource
# ---------------------------------------------------------------------------
@router.post("", response_model=ResourceRead, status_code=status.HTTP_201_CREATED)
async def create_resource(
    payload: ResourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resource = Resource(
        user_id=current_user.id,
        name=payload.name,
        url=payload.url,
        resource_type=payload.resource_type,
        interval_minutes=payload.interval_minutes,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)

    # Schedule the APScheduler job immediately
    schedule_resource(resource.id, resource.interval_minutes)

    return resource


# ---------------------------------------------------------------------------
# GET /resources/{id} — single resource
# ---------------------------------------------------------------------------
@router.get("/{resource_id}", response_model=ResourceRead)
async def get_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resource = await _get_owned_resource(db, resource_id, current_user.id)
    return resource


# ---------------------------------------------------------------------------
# PUT /resources/{id} — update resource
# ---------------------------------------------------------------------------
@router.put("/{resource_id}", response_model=ResourceRead)
async def update_resource(
    resource_id: int,
    payload: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resource = await _get_owned_resource(db, resource_id, current_user.id)

    interval_changed = False

    if payload.name is not None:
        resource.name = payload.name
    if payload.url is not None:
        resource.url = payload.url
    if payload.interval_minutes is not None and payload.interval_minutes != resource.interval_minutes:
        resource.interval_minutes = payload.interval_minutes
        interval_changed = True
    if payload.is_active is not None:
        resource.is_active = payload.is_active
        if payload.is_active:
            schedule_resource(resource.id, resource.interval_minutes)
        else:
            unschedule_resource(resource.id)

    await db.commit()
    await db.refresh(resource)

    if interval_changed and resource.is_active:
        reschedule_resource(resource.id, resource.interval_minutes)

    return resource


# ---------------------------------------------------------------------------
# DELETE /resources/{id}
# ---------------------------------------------------------------------------
@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resource = await _get_owned_resource(db, resource_id, current_user.id)
    unschedule_resource(resource.id)
    await db.delete(resource)
    await db.commit()


# ---------------------------------------------------------------------------
# GET /resources/{id}/logs — paginated check logs (last 50)
# ---------------------------------------------------------------------------
@router.get("/{resource_id}/logs", response_model=List[CheckLogRead])
async def get_resource_logs(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_resource(db, resource_id, current_user.id)  # ownership check
    result = await db.execute(
        select(CheckLog)
        .where(CheckLog.resource_id == resource_id)
        .order_by(desc(CheckLog.checked_at))
        .limit(50)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# POST /resources/{id}/check-now — immediate health check
# ---------------------------------------------------------------------------
@router.post("/{resource_id}/check-now", response_model=ResourceRead)
async def check_now(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resource = await _get_owned_resource(db, resource_id, current_user.id)

    # Run the check inline (bypasses scheduler)
    await scheduler_module.run_check(resource_id)

    # Reload fresh state from DB
    await db.refresh(resource)
    return resource


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_owned_resource(db: AsyncSession, resource_id: int, user_id: int) -> Resource:
    result = await db.execute(
        select(Resource).where(Resource.id == resource_id, Resource.user_id == user_id)
    )
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource
