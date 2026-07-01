"""
Native WebSocket connection manager — replaces Pusher.

All connected browser clients connect to GET /ws.
The manager broadcasts JSON messages to every active connection.
Event format:
  {
    "event": "<event-name>",
    "data":  { ... }
  }

Supported events (matching the spec):
  host-service-status-changed
  host-service-count-changed
  schedule-changed-event
  schedule-item-removed-event
  app-starting
  app-stopping
  monitoring-toggled
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.debug("WS client connected (total=%d)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.debug("WS client disconnected (total=%d)", len(self._connections))

    async def broadcast(self, event: str, data: dict) -> None:
        """Send a JSON message to all connected clients."""
        payload = json.dumps({"event": event, "data": data})
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    def broadcast_sync(self, event: str, data: dict) -> None:
        """
        Fire-and-forget broadcast from synchronous context
        (e.g., APScheduler callbacks running in the event loop).
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(event, data))
        except Exception as exc:
            logger.warning("broadcast_sync failed: %s", exc)


# Singleton used everywhere
ws_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Helper broadcast functions (mirror the old pusher_service API)
# ---------------------------------------------------------------------------

def broadcast_status_changed(
    host_id: int,
    host_name: str,
    service_type: str,
    old_status: str,
    new_status: str,
) -> None:
    ws_manager.broadcast_sync(
        "host-service-status-changed",
        {
            "host_id": host_id,
            "host_name": host_name,
            "service_type": service_type,
            "old_status": old_status,
            "new_status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def broadcast_count_changed(healthy: int, warning: int, problem: int, pending: int) -> None:
    ws_manager.broadcast_sync(
        "host-service-count-changed",
        {
            "healthy": healthy,
            "warning": warning,
            "problem": problem,
            "pending": pending,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def broadcast_schedule_changed(
    host_id: int,
    host_name: str,
    service_id: int,
    service_type: str,
    next_run: str,
) -> None:
    ws_manager.broadcast_sync(
        "schedule-changed-event",
        {
            "host_id": host_id,
            "host_name": host_name,
            "service_id": service_id,
            "service_type": service_type,
            "next_run": next_run,
        },
    )


def broadcast_schedule_item_removed(service_id: int) -> None:
    ws_manager.broadcast_sync(
        "schedule-item-removed-event",
        {"service_id": service_id},
    )


def broadcast_monitoring_toggled(enabled: bool) -> None:
    ws_manager.broadcast_sync(
        "monitoring-toggled",
        {
            "enabled": enabled,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def broadcast_app_event(event: str) -> None:
    """Send 'app-starting' or 'app-stopping'."""
    ws_manager.broadcast_sync(event, {"timestamp": datetime.now(timezone.utc).isoformat()})
