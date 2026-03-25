from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, JSON

from ..database import Base


class IntelligenceItem(Base):
    __tablename__ = "intelligence_items"

    id = Column(String(64), primary_key=True)
    source_name = Column(String(100), nullable=False, index=True)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    ai_brief = Column(JSON)
    domain = Column(String(50), nullable=False, index=True)
    severity = Column(Integer, default=0, index=True)
    india_score = Column(Integer, default=0, index=True)
    entities = Column(JSON)
    latitude = Column(Float)
    longitude = Column(Float)
    source_url = Column(Text)
    published_at = Column(DateTime(timezone=True), index=True)
    ingested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    vector_id = Column(String(64))
    raw_text = Column(Text)
    tags = Column(JSON, default=list)
    translated = Column(Boolean, default=False)
    original_lang = Column(String(10))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_name": self.source_name,
            "title": self.title,
            "summary": self.summary,
            "ai_brief": self.ai_brief,
            "domain": self.domain,
            "severity": self.severity,
            "india_score": self.india_score,
            "entities": self.entities or [],
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source_url": self.source_url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "tags": self.tags or [],
            "translated": self.translated,
            "original_lang": self.original_lang,
        }

    def to_ws_dict(self) -> dict:
        headline = self.ai_brief.get("headline", self.title[:80]) if self.ai_brief else self.title[:80]
        return {
            "id": self.id,
            "title": self.title,
            "domain": self.domain,
            "severity": self.severity,
            "india_score": self.india_score,
            "source": self.source_name,
            "headline": headline,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
