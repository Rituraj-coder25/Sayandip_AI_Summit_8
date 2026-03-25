from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from ..database import Base


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id = Column(String(64), primary_key=True)
    date = Column(String(20), nullable=False, unique=True, index=True)
    content = Column(Text)
    sections = Column(JSON)
    india_score = Column(Integer)
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    model_used = Column(String(100))
