"""Section 14 – GDELT Full Integration (upgraded, 7 themed query streams, 10-min poll)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ..base_connector import BaseConnector

GDELT_QUERIES = [
    ("global_conflict",  "conflict OR war OR military operation", "defense"),
    ("protests",         "protest OR demonstration OR riot OR unrest", "geopolitics"),
    ("disaster",         "earthquake OR flood OR cyclone OR wildfire disaster", "climate"),
    ("cyber",            "cyberattack OR ransomware OR data breach", "technology"),
    ("economics",        "sanctions OR tariff OR trade war OR economic crisis", "economics"),
    ("health",           "outbreak OR pandemic OR epidemic disease", "health"),
    ("india_focus",      "India OR South Asia OR Modi OR Pakistan", "geopolitics"),
]


class GDELTConnector(BaseConnector):
    SOURCE_NAME = "gdelt_events"
    POLL_INTERVAL_SECONDS = 600
    CACHE_TTL_SECONDS = 600

    async def fetch(self):
        tasks = []
        for theme, query, domain in GDELT_QUERIES:
            url = (
                f"https://api.gdeltproject.org/api/v2/doc/doc"
                f"?query={query.replace(' ', '+')}"
                f"&mode=ArtList&format=json&maxrecords=20&TIMESPAN=1440"
            )
            tasks.append(self._fetch_theme(theme, url, domain))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    async def _fetch_theme(self, theme: str, url: str, domain: str):
        try:
            data = await self.fetch_json(url)
            return {"theme": theme, "domain": domain, "data": data}
        except Exception:
            return {"theme": theme, "domain": domain, "data": None}

    async def parse(self, payload) -> list[dict]:
        signals = []
        for item in payload:
            theme = item.get("theme", "")
            domain = item.get("domain", "geopolitics")
            data = item.get("data")
            if not data:
                continue
            articles = data.get("articles", []) or data.get("data", []) or []
            for article in articles[:20]:
                title = article.get("title", "GDELT event")
                url = article.get("url", "")
                tone = float(article.get("tone", 0) or 0)
                seen = article.get("seendate", "")

                if tone < -5:
                    severity = 70
                elif tone < -2:
                    severity = 50
                else:
                    severity = 35

                india_score = 25 if theme == "india_focus" else 5

                signals.append(
                    self.std_signal(
                        id=url or f"gdelt-{theme}-{title[:30]}",
                        title=title[:120],
                        summary=f"GDELT {theme} | tone={tone:.1f}",
                        domain=domain,
                        severity=severity,
                        india_score=india_score,
                        url=url,
                        published_at=seen or datetime.now(UTC).isoformat(),
                        raw={"theme": theme, "tone": tone, "source_domain": article.get("domain", "")},
                        tags=["gdelt", theme],
                    )
                )
        return signals
