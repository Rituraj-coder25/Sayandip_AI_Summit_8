"""NGA – Navigational Warnings (free, no key, 1-hour poll)."""
from __future__ import annotations
import re
from datetime import UTC, datetime
import feedparser
from ..base_connector import BaseConnector

# Keywords that make a NAVWARN strategically significant
HIGH_SIGNIFICANCE_KEYWORDS = [
    "missile", "exercise", "weapons", "firing", "military",
    "cable", "pipeline", "prohibited", "exclusion zone",
    "live fire", "torpedo", "naval", "submarine",
]

class NGANavWarningsConnector(BaseConnector):
    SOURCE_NAME = "nga_navwarnings"
    POLL_INTERVAL_SECONDS = 3600   # 1 hour
    CACHE_TTL_SECONDS = 3600

    FEEDS = [
        "https://msi.nga.mil/api/publications/broadcast-warn?output=rss",
        "https://msi.nga.mil/api/publications/query?output=json&status=active&msgYear=2026&navArea=IV&includePoints=true",
    ]

    async def fetch(self):
        results = {}
        # RSS broadcast warnings
        try:
            results["rss"] = await self.fetch_text(self.FEEDS[0])
        except Exception:
            results["rss"] = None
        # JSON query for active warnings (NavArea IV = N Atlantic; covers multiple areas)
        for nav_area in ["IV", "XI", "XVI"]:   # Atlantic, Pacific, Indian Ocean
            try:
                url = (
                    f"https://msi.nga.mil/api/publications/query"
                    f"?output=json&status=active&navArea={nav_area}&includePoints=true"
                )
                results[f"json_{nav_area}"] = await self.fetch_json(url)
            except Exception:
                results[f"json_{nav_area}"] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals = []

        # Parse RSS feed
        if payload.get("rss"):
            feed = feedparser.parse(payload["rss"])
            for entry in feed.entries[:30]:
                title = (entry.get("title") or "NGA Nav Warning").strip()
                text = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")
                text_lower = (title + " " + text).lower()
                is_significant = any(kw in text_lower for kw in HIGH_SIGNIFICANCE_KEYWORDS)
                if not is_significant:
                    continue   # Skip routine navigation warnings
                signals.append(self.std_signal(
                    id=f"nga-{entry.get('id', title[:40])}",
                    title=f"NGA NavWarn: {title[:80]}",
                    summary=text[:400],
                    domain="defense",
                    severity=55,
                    india_score=10 if any(k in text_lower for k in ["india", "arabian", "bay of bengal", "indian ocean"]) else 5,
                    url=entry.get("link", "https://msi.nga.mil/"),
                    published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                    raw={"source": "nga_rss"},
                    tags=["nga", "navwarning", "maritime"],
                ))

        # Parse JSON responses
        for key in ["json_IV", "json_XI", "json_XVI"]:
            data = payload.get(key)
            if not data:
                continue
            publications = data if isinstance(data, list) else data.get("publications", []) or []
            for pub in publications[:20]:
                text = (pub.get("text") or pub.get("msgText") or "").lower()
                is_significant = any(kw in text for kw in HIGH_SIGNIFICANCE_KEYWORDS)
                if not is_significant:
                    continue
                signals.append(self.std_signal(
                    id=f"nga-json-{pub.get('msgNumber', pub.get('id', 'unknown'))}",
                    title=f"NGA NavWarn: {pub.get('subregion', key)} — {pub.get('msgNumber', '')}",
                    summary=(pub.get("text") or pub.get("msgText") or "")[:400],
                    domain="defense",
                    severity=55,
                    india_score=5,
                    url="https://msi.nga.mil/NavWarnings",
                    raw=pub,
                    tags=["nga", "navwarning", "maritime", key.split("_")[1]],
                ))

        return signals
