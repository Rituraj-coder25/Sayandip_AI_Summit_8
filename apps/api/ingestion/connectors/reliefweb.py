from datetime import UTC, datetime

from ..base_connector import BaseConnector


class ReliefWebConnector(BaseConnector):
    SOURCE_NAME = "un_reliefweb"
    POLL_INTERVAL_SECONDS = 1800
    URL = "https://api.reliefweb.int/v1/reports"

    async def fetch(self):
        try:
            response = await self.http.get(
                self.URL,
                params={
                    "appname": "goe-intelligence",
                    "limit": 20,
                    "profile": "list",
                },
                headers={
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return {"data": []}

    async def parse(self, payload):
        rows = payload.get("data", [])
        items = []
        for row in rows[:20]:
            fields = row.get("fields", {})
            items.append(
                {
                    "id": row.get("id") or fields.get("origin") or fields.get("title"),
                    "source_name": self.SOURCE_NAME,
                    "title": fields.get("title") or "ReliefWeb report",
                    "summary": fields.get("body-html") or fields.get("summary") or "Humanitarian update",
                    "raw_text": f"{fields.get('title', '')} {fields.get('body', '')}",
                    "domain": "climate",
                    "source_url": fields.get("url") or "",
                    "published_at": fields.get("date", {}).get("created") or datetime.now(UTC).isoformat(),
                    "tags": ["reliefweb", "humanitarian"],
                }
            )
        return items
