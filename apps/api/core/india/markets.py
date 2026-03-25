import json
from datetime import UTC, datetime


async def publish_market_snapshot(redis, snapshot: dict):
    payload = {
        **snapshot,
        "updated_at": snapshot.get("updated_at") or datetime.now(UTC).isoformat(),
    }
    await redis.set("goe:market_snapshot", json.dumps(payload))
    await redis.publish("goe:market_update", json.dumps({"type": "MARKET_UPDATE", "data": payload}))
    return payload
