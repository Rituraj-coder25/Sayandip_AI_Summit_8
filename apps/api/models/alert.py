from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, Text

from ..database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(64), primary_key=True)
    level = Column(String(20), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    intel_item_id = Column(String(64), index=True)
    triggered_by = Column(String(100))
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(255))
    acknowledged_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
