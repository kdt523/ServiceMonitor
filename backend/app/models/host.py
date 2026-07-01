"""
Host model — represents a monitored machine / endpoint.
A Host can have multiple HostService rows (http, https, ssl).
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Identity
    name = Column(String(255), nullable=False)                # Display name
    canonical_name = Column(String(255), nullable=True)       # FQDN / hostname
    url = Column(String(500), nullable=False)                  # Primary URL
    ipv4 = Column(String(45), nullable=True)
    ipv6 = Column(String(100), nullable=True)
    os = Column(String(100), nullable=True)                    # OS / platform label
    location = Column(String(255), nullable=True)             # Datacenter / region

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    owner = relationship("User", back_populates="hosts")
    services = relationship("HostService", back_populates="host", cascade="all, delete-orphan")
    event_logs = relationship("EventLog", back_populates="host", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="host", cascade="all, delete-orphan")

    @property
    def healthy_count(self) -> int:
        return sum(1 for s in self.services if s.status == "healthy")

    @property
    def warning_count(self) -> int:
        return sum(1 for s in self.services if s.status == "warning")

    @property
    def problem_count(self) -> int:
        return sum(1 for s in self.services if s.status == "problem")

    @property
    def pending_count(self) -> int:
        return sum(1 for s in self.services if s.status == "pending")

    def __repr__(self) -> str:
        return f"<Host id={self.id} name={self.name!r}>"
