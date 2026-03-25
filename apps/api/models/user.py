from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    role = Column(String(50), default="ANALYST")
    password_hash = Column(String(255))
    mfa_enabled = Column(Boolean, default=False)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))