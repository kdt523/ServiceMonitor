from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, func
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(30), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    hosts = relationship("Host", back_populates="owner", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        parts = [self.first_name or "", self.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        return name if name else self.email

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
