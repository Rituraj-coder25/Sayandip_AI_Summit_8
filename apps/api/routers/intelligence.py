from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.intelligence import IntelligenceItem
from ..schemas.intelligence import IntelligenceSearchRequest

router = APIRouter()


@router.get("")
async def list_intelligence(
    domain: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    query = select(IntelligenceItem).order_by(desc(IntelligenceItem.published_at)).limit(limit)
    if domain:
        query = query.where(IntelligenceItem.domain == domain)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"items": [item.to_dict() for item in items], "count": len(items)}


@router.post("/search")
async def search_intelligence(payload: IntelligenceSearchRequest, db: AsyncSession = Depends(get_db)):
    query = select(IntelligenceItem).order_by(desc(IntelligenceItem.published_at)).limit(payload.limit)
    if payload.domain:
        query = query.where(IntelligenceItem.domain == payload.domain)
    result = await db.execute(query)
    items = result.scalars().all()
    q = payload.query.lower()
    ranked = [
        item for item in items
        if q in (item.title or "").lower() or q in (item.summary or "").lower()
    ]
    return {"items": [item.to_dict() for item in ranked], "count": len(ranked)}
