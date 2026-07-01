"""
AppSettings model — a single-row table storing application-wide configuration.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from app.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)          # Always row id=1

    # General
    site_url = Column(String(500), nullable=True)
    site_name = Column(String(255), nullable=True, default="ServiceMonitor")

    # Monitoring engine
    monitoring_enabled = Column(Boolean, default=True, nullable=False)

    # SMTP
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True, default=587)
    smtp_user = Column(String(255), nullable=True)
    smtp_password = Column(String(255), nullable=True)
    smtp_from_name = Column(String(255), nullable=True)
    smtp_from_email = Column(String(255), nullable=True)
    smtp_use_tls = Column(Boolean, default=True)

    # Notification flags
    notify_via_email = Column(Boolean, default=False)
    notify_via_sms = Column(Boolean, default=False)

    # Notification recipient
    recipient_name = Column(String(255), nullable=True)
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(30), nullable=True)

    # Twilio
    twilio_sid = Column(String(255), nullable=True)
    twilio_auth_token = Column(String(255), nullable=True)
    twilio_from_phone = Column(String(30), nullable=True)

    # Webhook / Slack
    webhook_url = Column(String(500), nullable=True)
    webhook_enabled = Column(Boolean, default=False, nullable=False)

    updated_at = Column(DateTime, onupdate=func.now(), nullable=True)

    def __repr__(self) -> str:
        return f"<AppSettings monitoring={self.monitoring_enabled}>"
