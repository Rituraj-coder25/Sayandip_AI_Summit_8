from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector


class WHOConnector(BaseConnector):
    SOURCE_NAME = "who_outbreaks"
    POLL_INTERVAL_SECONDS = 1800
    URL = "https://www.who.int/rss-feeds/news-english.xml"

    async def fetch(self):
        return await self.fetch_text(self.URL)

    async def parse(self, payload):
        feed = feedparser.parse(payload)
        return [
            {
                "id": entry.get("id") or entry.get("link") or entry.get("title"),
                "source_name": self.SOURCE_NAME,
                "title": entry.get("title") or "WHO update",
                "summary": entry.get("summary") or "WHO health bulletin",
                "raw_text": f"{entry.get('title', '')} {entry.get('summary', '')}",
                "domain": "health",
                "source_url": entry.get("link"),
                "published_at": entry.get("published") or datetime.now(UTC).isoformat(),
                "tags": ["who", "health"],
            }
            for entry in feed.entries[:20]
        ]
