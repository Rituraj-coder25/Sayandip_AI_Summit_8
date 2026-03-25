"""Section 13 – Iran / LiveUAMap conflict events (5-min poll, fallback chain)."""
from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector

KEYWORD_SEVERITY = {
    "strike":   85,
    "attack":   80,
    "exchange": 75,
    "incident": 65,
}

GDELT_IRAN_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=Iran+attack+OR+Iran+strike+OR+Iran+military"
    "&mode=ArtList&format=json&maxrecords=15&TIMESPAN=1440"
)


class IranLiveUAMapConnector(BaseConnector):
    SOURCE_NAME = "iran_liveuamap"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 300

    async def fetch(self):
        # Option A – RSS
        for rss_url in [
            "https://liveuamap.com/en/iran/rss",
            "https://liveuamap.com/en/israel/rss",
        ]:
            try:
                text = await self.fetch_text(rss_url)
                if text and "<item>" in text.lower() or "<entry>" in text.lower():
                    return {"source": "rss", "data": text}
            except Exception:
                continue

        # Option B – HTML scrape for __initialState__
        try:
            html = await self.fetch_text("https://liveuamap.com/en/isr")
            if html and "__initialState__" in html:
                return {"source": "html", "data": html}
        except Exception:
            pass

        # Option C – GDELT proxy
        try:
            data = await self.fetch_json(GDELT_IRAN_URL)
            return {"source": "gdelt", "data": data}
        except Exception:
            pass

        return {"source": "none", "data": None}

    async def parse(self, payload) -> list[dict]:
        source = payload.get("source")
        data = payload.get("data")
        if not data:
            return []

        signals = []

        if source == "rss":
            parsed = feedparser.parse(data)
            for entry in parsed.entries[:20]:
                title = (entry.get("title") or "").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                severity = _keyword_severity(title + " " + summary)
                signals.append(
                    self.std_signal(
                        id=entry.get("id") or entry.get("link") or f"liveuamap-{title[:30]}",
                        title=title[:120],
                        summary=summary[:500],
                        domain="defense",
                        severity=severity,
                        india_score=5,
                        url=entry.get("link", ""),
                        published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                        raw={"source": "liveuamap_rss"},
                        tags=["conflict", "iran", "liveuamap"],
                    )
                )

        elif source == "gdelt":
            articles = data.get("articles", []) if isinstance(data, dict) else []
            for art in articles[:15]:
                title = art.get("title", "")
                url = art.get("url", "")
                tone = float(art.get("tone", 0) or 0)
                severity = _keyword_severity(title)
                if tone < -5:
                    severity = max(severity, 70)
                signals.append(
                    self.std_signal(
                        id=f"gdelt-iran-{url[-40:]}",
                        title=title[:120],
                        summary=f"GDELT proxy for Iran/Israel conflict monitoring",
                        domain="defense",
                        severity=severity,
                        india_score=5,
                        url=url,
                        raw={"source": "gdelt_proxy", "tone": tone},
                        tags=["conflict", "iran", "gdelt"],
                    )
                )

        return signals


def _keyword_severity(text: str) -> int:
    text_lower = text.lower()
    for kw, sev in KEYWORD_SEVERITY.items():
        if kw in text_lower:
            return sev
    return 65
