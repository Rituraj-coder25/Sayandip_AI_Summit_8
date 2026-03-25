from datetime import datetime, timedelta, timezone
import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.intelligence import IntelligenceItem

router = APIRouter()


@router.get("")
async def get_signals(
    request: Request,
    domain: str | None = None,
    min_severity: int = 0,
    min_india: int = 0,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(IntelligenceItem).order_by(desc(IntelligenceItem.published_at))
    if domain:
        query = query.where(IntelligenceItem.domain == domain)
    if min_severity:
        query = query.where(IntelligenceItem.severity >= min_severity)
    if min_india:
        query = query.where(IntelligenceItem.india_score >= min_india)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()
    return {"signals": [item.to_dict() for item in items], "count": len(items)}


@router.get("/live")
async def get_live_signals(request: Request, limit: int = 20):
    redis = request.app.state.redis
    keys = await redis.keys("goe:signal:*")
    keys = sorted(keys)[-limit:]

    signals: list[dict] = []
    for key in keys:
        raw = await redis.get(key)
        if raw:
            signals.append(json.loads(raw))

    signals.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return {"signals": signals}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    today = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(
        select(IntelligenceItem.domain, func.count(IntelligenceItem.id))
        .where(IntelligenceItem.published_at >= today)
        .group_by(IntelligenceItem.domain)
    )
    by_domain = {row[0]: row[1] for row in result.fetchall()}
    total = sum(by_domain.values())

    critical = await db.execute(
        select(func.count(IntelligenceItem.id))
        .where(IntelligenceItem.severity >= 75)
        .where(IntelligenceItem.published_at >= today)
    )

    return {
        "total_today": total,
        "by_domain": by_domain,
        "critical_24h": critical.scalar() or 0,
    }
