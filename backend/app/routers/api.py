"""
API router — JSON endpoints for check history, uptime %, and incidents.

These endpoints are used by:
  - Chart.js sparklines on the host detail page
  - Uptime badges
  - Incident history tables
  - The public status page
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.models.check_log import CheckLog
from app.models.host_service import HostService
from app.models.incident import Incident

router = APIRouter(prefix="/api", tags=["api"])


# ---------------------------------------------------------------------------
# Check History (for Chart.js graphs)
# ---------------------------------------------------------------------------

@router.get("/hosts/{host_id}/services/{service_type}/history")
async def service_history(
    host_id: int,
    service_type: str,
    limit: int = Query(default=288, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    Return recent check results for a host+service_type.
    Default limit=288 (one data point every 5 minutes for 24 hours).
    """
    # Find the service_id for this host+service_type
    svc_result = await db.execute(
        select(HostService.id).where(
            HostService.host_id == host_id,
            HostService.service_type == service_type,
        )
    )
    svc_id = svc_result.scalar_one_or_none()
    if svc_id is None:
        return JSONResponse([])

    result = await db.execute(
        select(CheckLog)
        .where(CheckLog.service_id == svc_id)
        .order_by(CheckLog.checked_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    # Return in chronological order (oldest first)
    return [
        {
            "checked_at": log.checked_at.isoformat() + "Z" if log.checked_at else None,
            "status": log.status,
            "response_time_ms": log.response_time_ms,
        }
        for log in reversed(logs)
    ]


# ---------------------------------------------------------------------------
# Uptime Percentage
# ---------------------------------------------------------------------------

@router.get("/hosts/{host_id}/services/{service_type}/uptime")
async def service_uptime(
    host_id: int,
    service_type: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate uptime % over 24h / 7d / 30d windows.
    Returns {"uptime_24h": 99.31, "uptime_7d": 98.75, "uptime_30d": 99.10}
    """
    # Find the service_id
    svc_result = await db.execute(
        select(HostService.id).where(
            HostService.host_id == host_id,
            HostService.service_type == service_type,
        )
    )
    svc_id = svc_result.scalar_one_or_none()
    if svc_id is None:
        return {"uptime_24h": None, "uptime_7d": None, "uptime_30d": None}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    uptimes = {}

    for label, delta in [("uptime_24h", timedelta(hours=24)),
                         ("uptime_7d", timedelta(days=7)),
                         ("uptime_30d", timedelta(days=30))]:
        since = now - delta
        result = await db.execute(
            select(
                func.count(CheckLog.id).filter(CheckLog.status == "healthy").label("healthy_count"),
                func.count(CheckLog.id).label("total_count"),
            )
            .where(
                CheckLog.service_id == svc_id,
                CheckLog.checked_at >= since,
            )
        )
        row = result.one()
        if row.total_count and row.total_count > 0:
            uptimes[label] = round(row.healthy_count * 100.0 / row.total_count, 2)
        else:
            uptimes[label] = None

    return uptimes


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@router.get("/hosts/{host_id}/incidents")
async def host_incidents(
    host_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return incident history for a host."""
    result = await db.execute(
        select(Incident)
        .where(Incident.host_id == host_id)
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    incidents = result.scalars().all()

    return [
        {
            "id": inc.id,
            "service_type": inc.service_type,
            "started_at": inc.started_at.isoformat() + "Z" if inc.started_at else None,
            "resolved_at": inc.resolved_at.isoformat() + "Z" if inc.resolved_at else None,
            "duration_seconds": inc.duration_seconds,
            "duration_display": inc.duration_display,
            "root_status": inc.root_status,
            "error_message": inc.error_message,
            "is_ongoing": inc.is_ongoing,
        }
        for inc in incidents
    ]


# ---------------------------------------------------------------------------
# Recent Incidents (all hosts — for dashboard)
# ---------------------------------------------------------------------------

@router.get("/incidents/recent")
async def recent_incidents(
    limit: int = Query(default=5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent incidents across all hosts."""
    from app.models.host import Host

    result = await db.execute(
        select(Incident, Host.name.label("host_name"))
        .join(Host, Host.id == Incident.host_id)
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    rows = result.all()

    return [
        {
            "id": inc.id,
            "host_name": host_name,
            "service_type": inc.service_type,
            "started_at": inc.started_at.isoformat() + "Z" if inc.started_at else None,
            "resolved_at": inc.resolved_at.isoformat() + "Z" if inc.resolved_at else None,
            "duration_display": inc.duration_display,
            "error_message": inc.error_message,
            "is_ongoing": inc.is_ongoing,
        }
        for inc, host_name in rows
    ]


# ---------------------------------------------------------------------------
# Overall Uptime (for dashboard card)
# ---------------------------------------------------------------------------

@router.get("/uptime/overall")
async def overall_uptime(
    db: AsyncSession = Depends(get_db),
):
    """Average uptime % across all active services over 24h."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(hours=24)

    result = await db.execute(
        select(
            func.count(CheckLog.id).filter(CheckLog.status == "healthy").label("healthy_count"),
            func.count(CheckLog.id).label("total_count"),
        )
        .where(CheckLog.checked_at >= since)
    )
    row = result.one()
    if row.total_count and row.total_count > 0:
        return {"uptime_24h": round(row.healthy_count * 100.0 / row.total_count, 2)}
    return {"uptime_24h": None}
