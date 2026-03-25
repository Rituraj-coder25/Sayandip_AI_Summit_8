import json

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/risk-score")
async def get_india_risk_score(request: Request):
    redis = request.app.state.redis
    cached = await redis.get("goe:india_risk_score_full")
    if cached:
        return json.loads(cached)

    from ..core.india.risk_score import compute_india_risk_score
    from ..database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await compute_india_risk_score(db, redis)
    return result


@router.get("/markets")
async def get_india_markets(request: Request):
    redis = request.app.state.redis
    market = await redis.get("goe:market_snapshot")
    if not market:
        return {"error": "Market data not yet available. Check back in a few minutes."}
    return json.loads(market)


@router.get("/signals")
async def get_india_signals(limit: int = 30):
    from sqlalchemy import desc, select

    from ..database import AsyncSessionLocal
    from ..models.intelligence import IntelligenceItem

    async with AsyncSessionLocal() as db:
        query = (
            select(IntelligenceItem)
            .where(IntelligenceItem.india_score >= 70)
            .order_by(desc(IntelligenceItem.severity), desc(IntelligenceItem.published_at))
            .limit(limit)
        )
        result = await db.execute(query)
        items = result.scalars().all()
    return {"signals": [item.to_dict() for item in items]}


@router.get("/brief")
async def get_india_brief(request: Request):
    analyst = request.app.state.analyst
    return await analyst.query(
        question=(
            "Generate a comprehensive India Strategic Assessment for today: "
            "current border situation (LOC + LAC), economic health, top threats, "
            "top opportunities, and 3 recommended priorities for the next 7 days."
        ),
        user_role="SENIOR_ANALYST",
        conversation_history=[],
    )
