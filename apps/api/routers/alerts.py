from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str


@router.get("")
async def get_alerts(
    request: Request,
    level: str | None = None,
    acknowledged: bool | None = None,
    limit: int = 50,
):
    from sqlalchemy import desc, select

    from ..database import AsyncSessionLocal
    from ..models.alert import Alert

    async with AsyncSessionLocal() as db:
        query = select(Alert).order_by(desc(Alert.created_at))
        if level:
            query = query.where(Alert.level == level.upper())
        if acknowledged is not None:
            query = query.where(Alert.acknowledged == acknowledged)
        query = query.limit(limit)
        result = await db.execute(query)
        alerts = result.scalars().all()

    return {
        "alerts": [
            {
                "id": alert.id,
                "level": alert.level,
                "title": alert.title,
                "description": alert.description,
                "intel_item_id": alert.intel_item_id,
                "acknowledged": alert.acknowledged,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
            }
            for alert in alerts
        ]
    }


@router.patch("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, body: AcknowledgeRequest, request: Request):
    from datetime import datetime, timezone
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models.alert import Alert

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            return {"error": "Alert not found"}
        alert.acknowledged = True
        alert.acknowledged_by = body.acknowledged_by
        alert.acknowledged_at = datetime.now(timezone.utc)
        await db.commit()

    return {"status": "acknowledged", "alert_id": alert_id}