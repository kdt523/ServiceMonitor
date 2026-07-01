from functools import lru_cache
from typing import Optional
import os
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://gonitor:gonitor@localhost:5432/gonitor"

    # JWT
    secret_key: str = "your-super-secret-jwt-key-change-this"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440        # 1 day
    remember_me_expire_minutes: int = 43200        # 30 days

    # Site
    site_url: str = "http://localhost:8000"
    site_name: str = "Gonitor"

    # SMTP (optional — leave blank to disable email notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "Gonitor"
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Notification preferences
    notify_via_email: bool = False
    notify_via_sms: bool = False

    # Notification recipient
    recipient_name: str = ""
    recipient_email: str = ""
    recipient_phone: str = ""

    # Twilio (optional — leave blank to disable SMS)
    twilio_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_phone: str = ""

    # Gemini AI assistant
    gemini_api_key: str = ""

    # Monitoring engine toggle (persisted to DB at runtime, this is the default)
    monitoring_enabled: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_db_url_scheme(cls, v: str) -> str:
        """
        Render (and some other platforms) inject DATABASE_URL as
        'postgresql://...' but asyncpg requires 'postgresql+asyncpg://...'.
        This validator silently fixes the scheme so no manual env-var
        editing is needed on Render.
        """
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore unknown env vars (e.g. old Pusher keys)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
