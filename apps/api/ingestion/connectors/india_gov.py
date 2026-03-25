"""
14th connector: Indian Government open feeds.
PIB, MEA, RBI, ISRO and related public institutional releases.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone

import feedparser

from ..base_connector import BaseConnector

INDIA_GOV_FEEDS = [
    ("PIB National", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"),
    ("PIB Defence", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=14"),
    ("PIB External", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=14"),
    ("MEA Press", "https://www.mea.gov.in/rss/pressreleases-rss.aspx"),
    ("MEA Speeches", "https://www.mea.gov.in/rss/speeches-statements-rss.aspx"),
    ("RBI Press", "https://www.rbi.org.in/Scripts/RSS.aspx?Id=316"),
    ("RBI Policy", "https://www.rbi.org.in/Scripts/RSS.aspx?Id=103"),
    ("ISRO News", "https://www.isro.gov.in/rss-feeds"),
    ("Finance Ministry", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=8"),
    ("Election Commission", "https://eci.gov.in/rss.aspx"),
]

HIGH_PRIORITY_KEYWORDS = [
    "defence",
    "security",
    "border",
    "missile",
    "nuclear",
    "isro",
    "launch",
    "china",
    "pakistan",
    "terror",
    "ceasefire",
    "sanctions",
    "treaty",
    "emergency",
    "strategic",
    "military exercise",
    "loc",
    "lac",
]


class IndiaGovConnector(BaseConnector):
    SOURCE_NAME = "india_gov_feeds"
    MIN_INTERVAL_SECONDS = 1800
    CACHE_TTL_SECONDS = 1700

    async def fetch_raw(self) -> dict:
        tasks = [self._fetch_one(name, url) for name, url in INDIA_GOV_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {"results": list(zip([feed[0] for feed in INDIA_GOV_FEEDS], results))}

    async def _fetch_one(self, name: str, url: str):
        return await asyncio.to_thread(feedparser.parse, url)

    async def parse(self, raw: dict) -> list[dict]:
        signals = []
        seen = set()

        for feed_name, parsed in raw.get("results", []):
            if isinstance(parsed, Exception):
                continue

            for entry in parsed.get("entries", [])[:10]:
                title = (entry.get("title") or "").strip()
                if not title or len(title) < 10:
                    continue

                fingerprint = hashlib.md5(title.lower().encode()).hexdigest()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()[:500]
                india_score = 85
                severity = 35
                lowered = f"{title} {summary}".lower()
                if any(keyword in lowered for keyword in HIGH_PRIORITY_KEYWORDS):
                    severity = 60
                    india_score = 95

                published_at = datetime.now(timezone.utc).isoformat()
                if entry.get("published_parsed"):
                    try:
                        published_at = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc).isoformat()
                    except Exception:
                        pass

                signals.append(
                    self.std_signal(
                        id=f"indgov_{fingerprint}",
                        title=title,
                        summary=summary,
                        domain="geopolitics",
                        severity=severity,
                        india_score=india_score,
                        url=entry.get("link", ""),
                        published_at=published_at,
                        raw={"feed": feed_name, "source": "India Government"},
                        source_name=feed_name,
                        tags=["india_gov", feed_name.lower().replace(" ", "_")],
                    )
                )

        return signals