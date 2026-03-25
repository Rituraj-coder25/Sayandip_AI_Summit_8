from typing import Any

from pydantic import BaseModel


class IndiaRiskResponse(BaseModel):
    score: int
    label: str
    color: str
    components: dict[str, Any]


class MarketSnapshotResponse(BaseModel):
    source: str
    timestamp: str | None = None
    nifty: dict[str, Any]
    sensex: dict[str, Any]
