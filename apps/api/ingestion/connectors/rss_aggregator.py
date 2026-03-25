from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector

GLOBAL_FEEDS = {
    "WHO": "https://www.who.int/rss-feeds/news-english.xml",
    "IAEA": "https://www.iaea.org/feeds/topnews",
    "ReliefWeb": "https://reliefweb.int/updates/rss.xml",
}

BHARATIYA_FEEDS = {
    "india_hindi": [
        ("Dainik Bhaskar", "https://www.bhaskar.com/rss-feed/1061/"),
        ("Amar Ujala", "https://www.amarujala.com/rss/breaking-news.xml"),
        ("NavBharat Times", "https://navbharattimes.indiatimes.com/rssarticleshow/48731087.cms"),
    ],
    "india_bengali": [
        ("Ananda Bazar", "https://www.anandabazar.com/feeds/google/ABPLTD01.xml"),
    ],
    "india_tamil": [
        ("Dinamalar", "https://www.dinamalar.com/rss/rss.xml"),
    ],
    "india_urdu": [
        ("Jang Pakistan", "https://jang.com.pk/rss/1.xml"),
        ("BBC Urdu", "https://feeds.bbci.co.uk/urdu/rss.xml"),
    ],
}


class RSSAggregatorConnector(BaseConnector):
    SOURCE_NAME = "rss_aggregator"
    POLL_INTERVAL_SECONDS = 900

    async def fetch(self):
        feeds = dict(GLOBAL_FEEDS)
        for language_feeds in BHARATIYA_FEEDS.values():
            for name, url in language_feeds:
                feeds[name] = url
        return {name: await self.fetch_text(url) for name, url in feeds.items()}

    async def parse(self, payload):
        signals = []
        for source, content in payload.items():
            parsed = feedparser.parse(content)
            for entry in parsed.entries[:10]:
                title = (entry.get("title") or f"{source} update").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or source).strip()
                signals.append(
                    self.std_signal(
                        id=entry.get("id") or entry.get("link") or title,
                        title=title,
                        summary=summary,
                        domain=_domain_for_source(source),
                        severity=35,
                        india_score=10 if source in GLOBAL_FEEDS else 35,
                        url=entry.get("link", ""),
                        published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                        raw={"feed": source},
                        source_name=source,
                        tags=["rss", source.lower().replace(" ", "_")],
                    )
                )
        return signals


def _domain_for_source(source: str) -> str:
    mapping = {
        "WHO": "society",
        "IAEA": "technology",
        "ReliefWeb": "climate",
        "PIB": "geopolitics",
    }
    return mapping.get(source, "geopolitics")