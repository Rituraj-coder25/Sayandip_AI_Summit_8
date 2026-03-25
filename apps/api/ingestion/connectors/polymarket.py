"""Section 10e – Polymarket Prediction Markets (5-min poll)."""
from __future__ import annotations

import random
from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings

TAGS_TO_FETCH = ["politics", "world", "ukraine"]
EXCLUDE_KEYWORDS = {"NBA", "NFL", "Oscar", "Grammy", "Super Bowl", "World Cup"}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class PolymarketConnector(BaseConnector):
    SOURCE_NAME = "polymarket_predictions"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 300

    async def fetch(self):
        if not settings.POLYMARKET_ENABLED:
            return []
        all_markets: list[dict] = []
        for tag in TAGS_TO_FETCH:
            url = f"https://gamma-api.polymarket.com/markets?closed=false&limit=50&tag={tag}"
            for attempt in range(3):
                try:
                    headers = {"User-Agent": random.choice(USER_AGENTS)}
                    data = await self.fetch_json(url, headers=headers)
                    if isinstance(data, list):
                        all_markets.extend(data)
                    elif isinstance(data, dict) and "markets" in data:
                        all_markets.extend(data["markets"])
                    break
                except Exception:
                    if attempt == 2:
                        pass
        return all_markets

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals = []
        for market in payload:
            question = market.get("question") or market.get("title") or ""
            # Filter sports/entertainment
            if any(kw.lower() in question.lower() for kw in EXCLUDE_KEYWORDS):
                continue
            volume = float(market.get("volume") or market.get("liquidityClob") or 0)
            prob = float(market.get("outcomePrices") or market.get("bestBid") or 50)
            # Normalize probability
            if prob > 1:
                prob = prob  # already percentage
            else:
                prob = prob * 100
            # Filter: volume > $50k or probability divergence >15pp from 50%
            if volume < 50000 and abs(prob - 50) < 15:
                continue

            slug = market.get("slug") or market.get("id") or question[:30]
            signals.append(
                self.std_signal(
                    id=f"poly-{slug}",
                    title=f"Polymarket: {question[:80]}",
                    summary=f"Probability {prob:.0f}% | Volume ${volume:,.0f}",
                    domain="geopolitics",
                    severity=40 if abs(prob - 50) > 30 else 30,
                    india_score=15 if "india" in question.lower() else 5,
                    url=f"https://polymarket.com/event/{slug}",
                    raw={"question": question, "probability": prob, "volume": volume},
                    tags=["prediction", "polymarket"],
                )
            )
        return signals
