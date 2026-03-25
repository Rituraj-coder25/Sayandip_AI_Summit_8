from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector


class IAEAConnector(BaseConnector):
    SOURCE_NAME = "iaea_nuclear"
    POLL_INTERVAL_SECONDS = 1800
    URL = "https://www.iaea.org/feeds/topnews"

    async def fetch(self):
        return await self.fetch_text(self.URL)

    async def parse(self, payload):
        feed = feedparser.parse(payload)
        return [
            {
                "id": entry.get("id") or entry.get("link") or entry.get("title"),
                "source_name": self.SOURCE_NAME,
                "title": entry.get("title") or "IAEA update",
                "summary": entry.get("summary") or "IAEA nuclear bulletin",
                "raw_text": f"{entry.get('title', '')} {entry.get('summary', '')}",
                "domain": "energy",
                "source_url": entry.get("link"),
                "published_at": entry.get("published") or datetime.now(UTC).isoformat(),
                "tags": ["iaea", "energy"],
            }
            for entry in feed.entries[:20]
        ]
