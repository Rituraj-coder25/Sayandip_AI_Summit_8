"""Section 15 – Global Health Feeds (15 WHO/CDC/ECDC sources, 30-min poll)."""
from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector

HEALTH_FEEDS = [
    ("WHO Global News",         "https://www.who.int/rss-feeds/news-english.xml"),
    ("WHO Africa Emergencies",  "https://www.afro.who.int/rss.xml"),
    ("WHO PAHO Americas",       "https://www.paho.org/en/rss.xml"),
    ("WHO SEARO Asia",          "https://www.who.int/southeastasia/rss-feeds"),
    ("CDC Newsroom",            "https://tools.cdc.gov/podcasts/feeds/rss/cdc-newsroom.xml"),
    ("CDC Health Alert Network","https://emergency.cdc.gov/han/feed/han_feed.xml"),
    ("CDC Travel Health",       "https://wwwnc.cdc.gov/travel/rss"),
    ("ECDC Communicable Disease","https://www.ecdc.europa.eu/en/news-events/rss"),
    ("ProMED Mail",             "https://promedmail.org/feed/"),
    ("OCHA Humanitarian",       "https://www.unocha.org/rss.xml"),
    ("MSF Doctors Without Borders","https://www.msf.org/feed"),
    ("IFRC Red Cross",          "https://www.ifrc.org/rss"),
    ("Outbreak News Today",     "https://outbreaknewstoday.com/feed/"),
    ("Health Map",              "https://www.healthmap.org/rss/en/rss.xml"),
    ("GOARN Alerts",            "https://extranet.who.int/goarn/sites/default/files/goarn_feed.xml"),
]

HEALTH_SEVERITY_KEYWORDS = {
    90: ["pandemic", "global health emergency", "pheic"],
    80: ["outbreak", "epidemic", "emergency declaration"],
    65: ["unusual disease", "novel pathogen", "unknown illness"],
    50: ["alert", "warning", "increased incidence"],
    35: ["surveillance", "monitoring", "update"],
}


def _health_severity(text: str) -> int:
    text_lower = text.lower()
    for sev, keywords in sorted(HEALTH_SEVERITY_KEYWORDS.items(), reverse=True):
        for kw in keywords:
            if kw in text_lower:
                return sev
    return 30


class GlobalHealthFeedsConnector(BaseConnector):
    SOURCE_NAME = "global_health_feeds"
    POLL_INTERVAL_SECONDS = 1800
    CACHE_TTL_SECONDS = 1800

    async def fetch(self):
        results = {}
        for name, url in HEALTH_FEEDS:
            try:
                results[name] = await self.fetch_text(url)
            except Exception:
                results[name] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals = []
        for source, text in payload.items():
            if not text:
                continue
            parsed = feedparser.parse(text)
            for entry in parsed.entries[:10]:
                title = (entry.get("title") or f"{source} update").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                severity = _health_severity(f"{title} {summary}")
                india_score = 15 if any(w in title.lower() for w in ("india", "south asia", "delhi")) else 5
                signals.append(
                    self.std_signal(
                        id=entry.get("id") or entry.get("link") or f"health-{source}-{title[:20]}",
                        title=title[:120],
                        summary=summary[:500],
                        domain="health",
                        severity=severity,
                        india_score=india_score,
                        url=entry.get("link", ""),
                        published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                        raw={"source": source},
                        source_name=source,
                        tags=["health", source.lower().replace(" ", "_")],
                    )
                )
        return signals
