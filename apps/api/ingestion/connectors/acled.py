from datetime import UTC, datetime, timedelta

from ...config import settings
from ..base_connector import BaseConnector


class ACLEDConnector(BaseConnector):
    SOURCE_NAME = "acled_conflicts"
    POLL_INTERVAL_SECONDS = 21600
    URL = "https://api.acleddata.com/acled/read/"

    async def fetch(self):
        if not settings.ACLED_API_KEY or not settings.ACLED_EMAIL:
            return {"data": []}
        params = {
            "key": settings.ACLED_API_KEY,
            "email": settings.ACLED_EMAIL,
            "event_date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "event_date_where": "BETWEEN",
            "event_date2": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d"),
            "limit": 50,
        }
        try:
            return await self.fetch_json(self.URL, params=params)
        except Exception:
            return {"data": []}

    async def parse(self, payload):
        rows = payload.get("data", [])
        items = []
        for row in rows[:50]:
            items.append(
                {
                    "id": row.get("event_id_cnty") or row.get("event_id_no_cnty") or row.get("event_date"),
                    "source_name": self.SOURCE_NAME,
                    "title": row.get("event_type") or "ACLED conflict event",
                    "summary": row.get("notes") or row.get("sub_event_type") or "Conflict update",
                    "raw_text": " ".join(filter(None, [row.get("event_type"), row.get("sub_event_type"), row.get("actor1"), row.get("actor2"), row.get("notes")])),
                    "domain": "defense",
                    "severity": 70 if row.get("fatalities") else 45,
                    "latitude": _to_float(row.get("latitude")),
                    "longitude": _to_float(row.get("longitude")),
                    "published_at": row.get("event_date") or datetime.now(UTC).isoformat(),
                    "tags": ["acled", "conflict"],
                }
            )
        return items


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None
