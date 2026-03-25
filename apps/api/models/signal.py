from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from ..database import Base


class RawSignal(Base):
    """Stores raw connector output before and after AI processing."""

    __tablename__ = "raw_signals"

    id = Column(String(64), primary_key=True)
    source_name = Column(String(100), index=True)
    raw_data = Column(JSON)
    payload = Column(JSON)
    external_id = Column(String(128), index=True)
    raw_text = Column(Text)
    processed = Column(Boolean, default=False, index=True)
    status = Column(String(30), default="NEW", index=True)
    published_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    ingested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    retry_count = Column(Integer, default=0)