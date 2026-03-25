"""Section 2 – Government Travel Advisories (30-min poll)."""
from __future__ import annotations

import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector

ADVISORY_FEEDS = [
    ("us_state",   "https://travel.state.gov/content/travel/en/traveladvisories/RSS.xml"),
    ("uk_fcdo",    "https://www.gov.uk/foreign-travel-advice.atom"),
    ("au_dfat",    "https://www.smartraveller.gov.au/sites/default/files/atom.xml"),
    ("nz_mfat",    "https://www.safetravel.govt.nz/rss.xml"),
    ("ca_dfatd",   "https://travel.gc.ca/travelling/advisories.rss"),
]

US_EMBASSY_FEEDS = [
    ("us_emb_th", "https://th.usembassy.gov/feed/"),
    ("us_emb_ae", "https://ae.usembassy.gov/feed/"),
    ("us_emb_de", "https://de.usembassy.gov/feed/"),
    ("us_emb_ua", "https://ua.usembassy.gov/feed/"),
    ("us_emb_mx", "https://mx.usembassy.gov/feed/"),
    ("us_emb_in", "https://in.usembassy.gov/feed/"),
    ("us_emb_pk", "https://pk.usembassy.gov/feed/"),
    ("us_emb_co", "https://co.usembassy.gov/feed/"),
    ("us_emb_pl", "https://pl.usembassy.gov/feed/"),
    ("us_emb_bd", "https://bd.usembassy.gov/feed/"),
    ("us_emb_it", "https://it.usembassy.gov/feed/"),
    ("us_emb_do", "https://do.usembassy.gov/feed/"),
    ("us_emb_mm", "https://mm.usembassy.gov/feed/"),
]

HEALTH_ADVISORY_FEEDS = [
    ("cdc_travel",  "https://tools.cdc.gov/api/v2/resources/media/316422.rss"),
    ("ecdc",        "https://www.ecdc.europa.eu/en/news-events/rss"),
    ("who",         "https://www.who.int/rss-feeds/news-english.xml"),
    ("who_africa",  "https://www.afro.who.int/rss.xml"),
]

INDIA_NEIGHBORS = {"IN", "PK", "BD", "LK", "NP", "BT", "MM", "AF"}

LEVEL_PATTERNS = [
    ("do_not_travel",                 re.compile(r"do\s+not\s+travel|level\s*4", re.I)),
    ("reconsider_travel",             re.compile(r"reconsider\s+travel|level\s*3", re.I)),
    ("exercise_increased_caution",    re.compile(r"exercise\s+increased\s+caution|level\s*2", re.I)),
    ("exercise_normal_precautions",   re.compile(r"exercise\s+normal\s+precautions|level\s*1", re.I)),
]

LEVEL_SEVERITY = {
    "do_not_travel": 90,
    "reconsider_travel": 70,
    "exercise_increased_caution": 50,
    "exercise_normal_precautions": 20,
}


def _detect_level(text: str) -> str:
    for level, pat in LEVEL_PATTERNS:
        if pat.search(text):
            return level
    return "exercise_normal_precautions"


def _guess_country_code(text: str) -> str:
    # Very simple heuristic – return first 2-char uppercase token
    for tok in text.split():
        clean = tok.strip("()[].,;:\"'")
        if len(clean) == 2 and clean.isalpha() and clean.isupper():
            return clean
    return "XX"


class GovAdvisoryConnector(BaseConnector):
    SOURCE_NAME = "gov_advisories"
    POLL_INTERVAL_SECONDS = 1800
    CACHE_TTL_SECONDS = 1800

    async def fetch(self):
        all_feeds = ADVISORY_FEEDS + US_EMBASSY_FEEDS + HEALTH_ADVISORY_FEEDS
        results = {}
        for source, url in all_feeds:
            try:
                text = await self.fetch_text(url)
                results[source] = text
            except Exception:
                results[source] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals = []
        for source, text in payload.items():
            if text is None:
                continue
            parsed = feedparser.parse(text)
            for entry in parsed.entries[:10]:
                title = (entry.get("title") or "Advisory").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                combined = f"{title} {summary}"
                level = _detect_level(combined)
                severity = LEVEL_SEVERITY[level]
                cc = _guess_country_code(title)
                india_score = 15 if cc in INDIA_NEIGHBORS else 5
                if level == "do_not_travel" and cc in INDIA_NEIGHBORS:
                    india_score += 15
                date_str = entry.get("published") or entry.get("updated") or datetime.now(UTC).isoformat()
                signals.append(
                    self.std_signal(
                        id=f"advisory-{source}-{cc}-{date_str[:10]}",
                        title=title,
                        summary=summary[:500],
                        domain="geopolitics",
                        severity=severity,
                        india_score=min(100, india_score),
                        url=entry.get("link", ""),
                        published_at=date_str,
                        raw={"advisory_level": level, "issuing_gov": source, "country": cc},
                        tags=["advisory", source, cc.lower()],
                    )
                )
                # Cache per-country
                await self.redis.setex(f"goe:advisory:{cc}", 1800, title)
        return signals
