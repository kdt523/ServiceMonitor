"""
HostService model — one row per (host × service_type).

service_type values:
  'http'  — plain HTTP check (status 200 required)
  'https' — HTTPS check (status 200 + TLS handshake)
  'ssl'   — SSL certificate expiry monitoring
  'tcp'   — raw TCP port connectivity check
  'ping'  — ICMP ping (network reachability)
  'dns'   — DNS hostname resolution
  'ssh'   — TCP connect to port 22 (SSH daemon check)
  'ftp'   — TCP connect to port 21 (FTP server check)
  'smtp'  — TCP connect + 220 banner grab (mail server check)

status values:
  'healthy'  — all good
  'warning'  — degraded (SSL expiry 7–30 days)
  'problem'  — down or critical (SSL < 7 days)
  'pending'  — never checked yet
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from app.database import Base

SERVICE_TYPES = ("http", "https", "ssl", "tcp", "ping", "dns", "ssh", "ftp", "smtp")
STATUSES = ("healthy", "warning", "problem", "pending")

# Default ports for service types that use custom ports
DEFAULT_PORTS = {
    "tcp":  80,
    "ssh":  22,
    "ftp":  21,
    "smtp": 587,
}


class HostService(Base):
    __tablename__ = "host_services"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True)

    service_type = Column(String(20), nullable=False)          # see SERVICE_TYPES
    is_active = Column(Boolean, default=False, nullable=False)

    # Scheduling — flexible: one of minutes / hours / days is non-zero
    interval_minutes = Column(Integer, nullable=False, default=5)

    # Runtime state
    status = Column(String(10), nullable=False, default="pending")
    last_checked_at = Column(DateTime, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    ssl_days_remaining = Column(Integer, nullable=True)        # Only for ssl type
    last_error = Column(String(500), nullable=True)

    # Service-specific configuration
    port = Column(Integer, nullable=True)                      # Custom port for tcp/ssh/ftp/smtp
    keyword_check = Column(Text, nullable=True)                # Keyword body assertion for http/https
    custom_headers = Column(JSON, nullable=True)               # Custom HTTP headers as {"key": "value"}

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    host = relationship("Host", back_populates="services")
    check_logs = relationship("CheckLog", back_populates="service", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="service", cascade="all, delete-orphan")

    @property
    def effective_port(self) -> int | None:
        """Return configured port or the default for this service type."""
        if self.port is not None:
            return self.port
        return DEFAULT_PORTS.get(self.service_type)

    def __repr__(self) -> str:
        return (
            f"<HostService id={self.id} host_id={self.host_id} "
            f"type={self.service_type!r} status={self.status!r}>"
        )
