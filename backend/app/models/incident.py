"""
Incident model — tracks downtime periods per host+service.

Each row represents a single outage:
  - started_at:  when the service first went to "problem"
  - resolved_at: when it recovered (NULL = still ongoing)
  - duration_seconds: computed on resolve

Used for incident history, MTTR/MTBF calculations.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    host_service_id = Column(Integer, ForeignKey("host_services.id", ondelete="CASCADE"), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    service_type = Column(String(20), nullable=False)

    started_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)          # NULL = still ongoing
    duration_seconds = Column(Integer, nullable=True)      # filled on resolve

    root_status = Column(String(20), nullable=False)       # problem / warning
    error_message = Column(Text, nullable=True)

    # Relationships
    service = relationship("HostService", back_populates="incidents")
    host = relationship("Host", back_populates="incidents")

    __table_args__ = (
        Index("ix_incidents_host_id", "host_id"),
        Index("ix_incidents_started_at", started_at.desc()),
    )

    @property
    def is_ongoing(self) -> bool:
        return self.resolved_at is None

    @property
    def duration_display(self) -> str:
        """Human-readable duration string."""
        if self.duration_seconds is None:
            return "Ongoing"
        s = self.duration_seconds
        if s < 60:
            return f"{s}s"
        elif s < 3600:
            return f"{s // 60}m {s % 60}s"
        else:
            h = s // 3600
            m = (s % 3600) // 60
            return f"{h}h {m}m"

    def __repr__(self) -> str:
        return (
            f"<Incident id={self.id} host_service_id={self.host_service_id} "
            f"started_at={self.started_at} resolved={'yes' if self.resolved_at else 'no'}>"
        )
