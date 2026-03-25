"""
Composite India Strategic Risk Score (0-100).
Computed from live PostgreSQL data and cached in Redis.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ...models.intelligence import IntelligenceItem

logger = logging.getLogger("goe.risk")


async def compute_india_risk_score(db, redis_client) -> dict:
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    border_q = await db.execute(
        select(func.avg(IntelligenceItem.severity), func.count(IntelligenceItem.id))
        .where(IntelligenceItem.india_score >= 70)
        .where(IntelligenceItem.domain.in_(["defense", "geopolitics"]))
        .where(IntelligenceItem.published_at >= cutoff_7d)
    )
    border_avg, border_cnt = border_q.fetchone()
    border_score = min(100, float(border_avg or 0) * 0.6 + int(border_cnt or 0) * 2)

    economic_score = 25
    market_raw = await redis_client.get("goe:market_snapshot")
    if market_raw:
        try:
            market = json.loads(market_raw)
            inr = None
            if isinstance(market.get("forex"), dict):
                inr = float(market.get("forex", {}).get("INR", 83.5))
            elif market.get("USDINR") not in (None, ""):
                try:
                    inr = float(market.get("USDINR"))
                except Exception:
                    inr = 83.5
            if inr is not None:
                if inr > 87:
                    economic_score = 70
                elif inr > 85:
                    economic_score = 45
                elif inr < 82:
                    economic_score = 15
        except Exception:
            pass

    regional_q = await db.execute(
        select(func.avg(IntelligenceItem.severity))
        .where(IntelligenceItem.india_score.between(40, 69))
        .where(IntelligenceItem.published_at >= cutoff_24h)
    )
    regional_score = float(regional_q.scalar() or 25)

    global_q = await db.execute(
        select(func.avg(IntelligenceItem.severity))
        .where(IntelligenceItem.severity >= 70)
        .where(IntelligenceItem.india_score < 40)
        .where(IntelligenceItem.published_at >= cutoff_24h)
    )
    global_score = float(global_q.scalar() or 20) * 0.35

    domestic_q = await db.execute(
        select(func.avg(IntelligenceItem.severity))
        .where(IntelligenceItem.india_score >= 90)
        .where(IntelligenceItem.domain == "society")
        .where(IntelligenceItem.published_at >= cutoff_24h)
    )
    domestic_score = float(domestic_q.scalar() or 15)

    weights = await _get_feedback_weights(redis_client)
    composite = (
        border_score * weights["border"]
        + economic_score * weights["economic"]
        + regional_score * weights["regional"]
        + global_score * weights["global"]
        + domestic_score * weights["domestic"]
    )
    composite = min(100, max(0, round(composite)))
    color = "red" if composite >= 70 else "amber" if composite >= 40 else "green"

    result = {
        "score": composite,
        "color": color,
        "label": "ELEVATED" if composite >= 70 else "MODERATE" if composite >= 40 else "LOW",
        "components": {
            "border_tension": round(border_score),
            "economic_risk": round(economic_score),
            "regional_stability": round(regional_score),
            "global_environment": round(global_score),
            "domestic": round(domestic_score),
        },
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis_client.setex("goe:india_risk_score_full", 900, json.dumps(result))
    await redis_client.set("goe:india_risk_score", str(composite))
    return result


async def _get_feedback_weights(redis_client) -> dict:
    raw = await redis_client.get("goe:risk_score_weights")
    if raw:
        return json.loads(raw)
    return {
        "border": 0.30,
        "economic": 0.25,
        "regional": 0.20,
        "global": 0.15,
        "domestic": 0.10,
    }


async def analyst_feedback_reweight(redis_client):
    feedback_raw = await redis_client.lrange("goe:analyst_feedback", 0, -1)
    if len(feedback_raw) < 50:
        return

    ratings = [json.loads(item) for item in feedback_raw]
    component_ratings = {key: [] for key in ["border", "economic", "regional", "global", "domestic"]}
    for rating in ratings:
        component = rating.get("component")
        if component in component_ratings:
            component_ratings[component].append(rating.get("rating", 0))

    current = await _get_feedback_weights(redis_client)
    for component, values in component_ratings.items():
        if len(values) >= 10:
            accuracy = sum(1 for value in values if value == 1) / len(values)
            delta = (accuracy - 0.5) * 0.04
            current[component] = max(0.05, min(0.45, current[component] + delta))

    total = sum(current.values()) or 1.0
    normalised = {key: round(value / total, 4) for key, value in current.items()}
    await redis_client.set("goe:risk_score_weights", json.dumps(normalised))
    logger.info("Risk score weights updated: %s", normalised)