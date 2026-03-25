from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, String, Text

from ..database import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(String(64), primary_key=True)
    created_by = Column(String(64))
    title = Column(Text)
    hypothesis = Column(Text)
    tree_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
