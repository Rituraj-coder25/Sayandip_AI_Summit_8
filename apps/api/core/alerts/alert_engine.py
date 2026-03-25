"""
Alert engine - evaluates every new IntelligenceItem and fires alerts.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from ...models.alert import Alert

logger = logging.getLogger("goe.alerts")


class AlertEngine:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def evaluate(self, item, db):
        level = self._compute_level(item)
        if level is None:
            return

        alert = Alert(
            id=str(uuid.uuid4()),
            level=level,
            title=item.ai_brief.get("headline", item.title[:80]) if item.ai_brief else item.title[:80],
            description=item.ai_brief.get("india_impact", "") if item.ai_brief else "",
            intel_item_id=item.id,
            triggered_by="alert_engine_v4",
        )
        db.add(alert)
        await db.flush()

        await self.redis.publish(
            "goe:alerts",
            json.dumps(
                {
                    "type": "NEW_ALERT",
                    "data": {
                        "id": alert.id,
                        "level": level,
                        "title": alert.title,
                        "description": alert.description,
                        "domain": item.domain,
                        "severity": item.severity,
                        "india_score": item.india_score,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            ),
        )
        logger.info("Alert fired: %s - %s", level, alert.title[:60])
        return alert

    def _compute_level(self, item) -> str | None:
        severity, india_score = item.severity, item.india_score
        title = item.title.lower()

        flash_keywords = ["nuclear launch", "war declared", "invasion", "direct attack on india", "coup", "magnitude 8", "magnitude 9"]
        if any(keyword in title for keyword in flash_keywords) or (severity >= 90 and india_score >= 80):
            return "FLASH"
        if severity >= 75 or (severity >= 65 and india_score >= 75):
            return "URGENT"
        if severity >= 60 or india_score >= 70:
            return "PRIORITY"
        if severity >= 45 or india_score >= 55:
            return "ROUTINE"
        return None