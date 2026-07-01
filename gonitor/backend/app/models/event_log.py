"""
EventLog model — persistent audit/event log for the application.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


EVENT_TYPES = (
    "info",
    "warning",
    "error",
    "host_added",
    "host_updated",
    "host_deleted",
    "service_enabled",
    "service_disabled",
    "status_changed",
    "check_completed",
    "notification_sent",
    "incident_opened",
    "incident_resolved",
)


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True)
    service_type = Column(String(20), nullable=True)          # http | https | ssl | tcp | ping | dns | ssh | ftp | smtp
    event_type = Column(String(30), nullable=False)           # See EVENT_TYPES above
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationship
    host = relationship("Host", back_populates="event_logs")

    def __repr__(self) -> str:
        return (
            f"<EventLog id={self.id} type={self.event_type!r} "
            f"host_id={self.host_id} created_at={self.created_at}>"
        )
