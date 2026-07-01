"""
CheckLog model — one row per health check execution on a HostService.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


class CheckLog(Base):
    __tablename__ = "check_logs"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("host_services.id", ondelete="CASCADE"), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, index=True)

    status = Column(String(10), nullable=False)          # healthy | warning | problem
    response_time_ms = Column(Integer, nullable=True)
    ssl_days_remaining = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    checked_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    service = relationship("HostService", back_populates="check_logs")

    def __repr__(self) -> str:
        return (
            f"<CheckLog id={self.id} service_id={self.service_id} "
            f"status={self.status!r} checked_at={self.checked_at}>"
        )
