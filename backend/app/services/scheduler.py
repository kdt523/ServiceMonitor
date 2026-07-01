"""
APScheduler service — manages one AsyncIOScheduler job per HostService.

Job ID scheme: svc_{service_id}
MonitorMap:    dict[service_id → job_id]

Design:
- Each job creates its OWN DB session via AsyncSessionFactory.
- coalesce=True + misfire_grace_time prevent job pile-up.
- Jobs are paused globally when monitoring_enabled=False.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func, delete

from app.database import AsyncSessionFactory
from app.models.host_service import HostService
from app.models.host import Host
from app.models.check_log import CheckLog
from app.models.incident import Incident
from app.services.health_checker import run_health_check
from app.services.ws_manager import (
    broadcast_status_changed,
    broadcast_count_changed,
    broadcast_schedule_changed,
    broadcast_schedule_item_removed,
)

logger = logging.getLogger(__name__)

# Singleton scheduler
scheduler = AsyncIOScheduler()

# MonitorMap: service_id → APScheduler job_id string
MonitorMap: dict[int, str] = {}

# Global monitoring toggle
_monitoring_enabled: bool = True

# Maximum check_logs rows per service (retention policy)
MAX_CHECK_LOGS_PER_SERVICE = 1000


# ---------------------------------------------------------------------------
# Global monitoring toggle
# ---------------------------------------------------------------------------

def set_monitoring_enabled(enabled: bool) -> None:
    global _monitoring_enabled
    _monitoring_enabled = enabled
    if enabled:
        scheduler.resume()
    else:
        scheduler.pause()
    logger.info("Monitoring %s", "enabled" if enabled else "paused")


def is_monitoring_enabled() -> bool:
    return _monitoring_enabled


# ---------------------------------------------------------------------------
# Core job
# ---------------------------------------------------------------------------

async def run_check(service_id: int) -> None:
    """
    Perform a health check for a single HostService.
    1. Fetch service + host
    2. Run the appropriate check (with port/keyword/headers)
    3. Persist CheckLog (with host_id)
    4. Update service status fields
    5. If status changed → create/resolve incident
    6. If status changed → broadcast WebSocket + count update + notify
    7. Enforce retention policy on check_logs
    8. Commit
    """
    async with AsyncSessionFactory() as session:
        try:
            # 1. Fetch service
            svc_result = await session.execute(
                select(HostService).where(HostService.id == service_id)
            )
            service: HostService | None = svc_result.scalar_one_or_none()
            if service is None:
                logger.warning("run_check: service %d not found, skipping", service_id)
                return

            host_result = await session.execute(
                select(Host).where(Host.id == service.host_id)
            )
            host: Host | None = host_result.scalar_one_or_none()
            if host is None:
                return

            old_status = service.status

            # 2. Run the check — pass service-specific config
            check_result = await run_health_check(
                service_type=service.service_type,
                url=host.url,
                port=service.port,
                keyword=service.keyword_check,
                headers=service.custom_headers,
                canonical_name=host.canonical_name,
            )

            new_status = check_result["status"]
            response_time_ms = check_result.get("response_time_ms")
            ssl_days = check_result.get("ssl_days_remaining")
            error_msg = check_result.get("error_message")

            # 3. Persist log (with host_id for history queries)
            log = CheckLog(
                service_id=service_id,
                host_id=host.id,
                status=new_status,
                response_time_ms=response_time_ms,
                ssl_days_remaining=ssl_days,
                error_message=error_msg,
                checked_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            session.add(log)

            # 4. Update service
            service.status = new_status
            service.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            service.response_time_ms = response_time_ms
            service.ssl_days_remaining = ssl_days
            service.last_error = error_msg

            # 5. Incident tracking on status change
            if old_status != new_status:
                await _handle_incident(session, service, host, old_status, new_status, error_msg)

            await session.commit()

            # 6. Broadcast + notify on status change
            if old_status != new_status:
                logger.info(
                    "Service %d (%s/%s) status: %s → %s",
                    service_id, host.name, service.service_type, old_status, new_status,
                )
                broadcast_status_changed(
                    host.id, host.name, service.service_type, old_status, new_status
                )

                # Broadcast updated counts
                await _broadcast_counts(session)

                # Notifications (skips pending → anything)
                if old_status != "pending":
                    try:
                        from app.services.notification_service import send_notifications
                        await send_notifications(host, service, old_status, new_status)
                    except Exception as ne:
                        logger.warning("Notification failed: %s", ne)

            # 7. Retention: keep only the last N rows per service
            await _enforce_retention(session, service_id)

        except Exception as exc:
            logger.exception("run_check error for service %d: %s", service_id, exc)
            await session.rollback()


async def _handle_incident(session, service, host, old_status, new_status, error_msg):
    """Create or resolve incidents on status transitions."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Status changed TO problem → open an incident
    if new_status == "problem" and old_status != "problem":
        incident = Incident(
            host_service_id=service.id,
            host_id=host.id,
            service_type=service.service_type,
            started_at=now,
            root_status="problem",
            error_message=error_msg,
        )
        session.add(incident)

    # Status changed FROM problem to healthy → resolve the open incident
    if new_status == "healthy" and old_status == "problem":
        result = await session.execute(
            select(Incident)
            .where(
                Incident.host_service_id == service.id,
                Incident.resolved_at.is_(None),
            )
            .order_by(Incident.started_at.desc())
            .limit(1)
        )
        open_incident = result.scalar_one_or_none()
        if open_incident:
            open_incident.resolved_at = now
            open_incident.duration_seconds = int((now - open_incident.started_at).total_seconds())


async def _enforce_retention(session, service_id: int) -> None:
    """Delete oldest check_logs for a service if count exceeds MAX_CHECK_LOGS_PER_SERVICE."""
    try:
        count_result = await session.execute(
            select(func.count(CheckLog.id)).where(CheckLog.service_id == service_id)
        )
        total = count_result.scalar()
        if total and total > MAX_CHECK_LOGS_PER_SERVICE:
            # Get the id of the Nth-newest row
            cutoff_result = await session.execute(
                select(CheckLog.id)
                .where(CheckLog.service_id == service_id)
                .order_by(CheckLog.checked_at.desc())
                .offset(MAX_CHECK_LOGS_PER_SERVICE)
                .limit(1)
            )
            cutoff_id = cutoff_result.scalar()
            if cutoff_id:
                await session.execute(
                    delete(CheckLog)
                    .where(
                        CheckLog.service_id == service_id,
                        CheckLog.id <= cutoff_id,
                    )
                )
                await session.commit()
    except Exception as exc:
        logger.warning("Retention cleanup failed for service %d: %s", service_id, exc)


async def _broadcast_counts(session) -> None:
    """Query and broadcast current healthy/warning/problem/pending counts."""
    try:
        result = await session.execute(
            select(HostService.status, func.count(HostService.id))
            .where(HostService.is_active == True)  # noqa: E712
            .group_by(HostService.status)
        )
        counts = {row[0]: row[1] for row in result.fetchall()}
        broadcast_count_changed(
            healthy=counts.get("healthy", 0),
            warning=counts.get("warning", 0),
            problem=counts.get("problem", 0),
            pending=counts.get("pending", 0),
        )
    except Exception as exc:
        logger.warning("_broadcast_counts failed: %s", exc)


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

def _job_id(service_id: int) -> str:
    return f"svc_{service_id}"


def schedule_service(service_id: int, interval_minutes: int) -> None:
    """Add (or replace) an interval job for the given HostService."""
    jid = _job_id(service_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)

    scheduler.add_job(
        run_check,
        trigger="interval",
        minutes=interval_minutes,
        args=[service_id],
        id=jid,
        coalesce=True,
        misfire_grace_time=30,
        replace_existing=True,
    )
    MonitorMap[service_id] = jid
    logger.info("Scheduled job %s every %d min", jid, interval_minutes)

    # Broadcast schedule change
    broadcast_schedule_changed(0, "", service_id, "", "")


def unschedule_service(service_id: int) -> None:
    """Remove the scheduler job for a service."""
    jid = _job_id(service_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
    MonitorMap.pop(service_id, None)
    logger.info("Removed job %s", jid)
    broadcast_schedule_item_removed(service_id)


def reschedule_service(service_id: int, interval_minutes: int) -> None:
    """Update the interval of an existing service job (or create it)."""
    jid = _job_id(service_id)
    if scheduler.get_job(jid):
        scheduler.reschedule_job(jid, trigger="interval", minutes=interval_minutes)
        logger.info("Rescheduled %s to every %d min", jid, interval_minutes)
    else:
        schedule_service(service_id, interval_minutes)


def get_schedule_info() -> list[dict]:
    """Return list of dicts describing all scheduled jobs (for the Schedule page)."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "job_id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return jobs


async def load_and_schedule_all() -> None:
    """Startup: fetch all active services and schedule them."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(HostService).where(
                HostService.is_active == True  # noqa: E712
            )
        )
        services = result.scalars().all()
        for svc in services:
            schedule_service(svc.id, svc.interval_minutes)
        logger.info("Loaded and scheduled %d active service(s)", len(services))


async def run_check_now(service_id: int) -> None:
    """Manual trigger — run check immediately outside scheduler cycle."""
    await run_check(service_id)
