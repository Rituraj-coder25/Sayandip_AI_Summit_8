from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IntelligenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_name: str
    title: str
    summary: str | None = None
    ai_brief: dict[str, Any] | None = None
    domain: str
    severity: int
    india_score: int
    entities: list[dict[str, Any]] = []
    latitude: float | None = None
    longitude: float | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    ingested_at: datetime | None = None
    tags: list[str] = []


class IntelligenceSearchRequest(BaseModel):
    query: str
    limit: int = 10
    domain: str | None = None
