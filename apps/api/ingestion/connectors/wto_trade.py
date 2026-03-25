"""Section 10g – WTO Trade Policy (RSS feeds, 1-hour poll)."""
from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector
from ...config import settings

WTO_FEEDS = [
    ("wto_news", "https://www.wto.org/english/news_e/news_e_rss_en.xml"),
    ("wto_tpr",  "https://tpr.wto.org/en/feed"),
]


class WTOTradeConnector(BaseConnector):
    SOURCE_NAME = "wto_trade"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        if not settings.WTO_FEEDS_ENABLED:
            return []
        results = {}
        for name, url in WTO_FEEDS:
            try:
                results[name] = await self.fetch_text(url)
            except Exception:
                results[name] = None
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals = []
        for source, text in payload.items():
            if not text:
                continue
            parsed = feedparser.parse(text)
            for entry in parsed.entries[:15]:
                title = (entry.get("title") or "WTO Update").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                signals.append(
                    self.std_signal(
                        id=entry.get("id") or entry.get("link") or f"wto-{title[:30]}",
                        title=title,
                        summary=summary[:500],
                        domain="economics",
                        severity=35,
                        india_score=15 if "india" in title.lower() else 5,
                        url=entry.get("link", ""),
                        published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                        raw={"source": source},
                        tags=["trade", "wto", source],
                    )
                )
        return signals
