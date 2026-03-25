"""
Checks a scraped item against:
1. Redis set of recently seen title hashes (from all RSS connectors)
2. ChromaDB similarity check (catches near-duplicates with different wording)

The world-monitor feed and RSS feeds often cover the same story.
This prevents the same event from appearing twice in the live feed.
"""
import hashlib
import logging

import redis.asyncio as aioredis

logger = logging.getLogger("goe.agent.dedup")

SEEN_KEY = "goe:agent_seen_titles"   # Redis set, same key used by mass_rss.py
SEEN_TTL = 86400                       # 24 hours


class AgentDeduplicator:

    def __init__(self, redis_client: aioredis.Redis, vector_store=None):
        self.redis  = redis_client
        self.vector = vector_store    # optional ChromaDB for semantic dedup

    def _hash(self, title: str) -> str:
        return hashlib.md5(title.lower().strip().encode()).hexdigest()

    async def is_duplicate(self, title: str, text: str = "") -> bool:
        """
        Returns True if this item has already been seen recently.
        Fast path: title hash in Redis set.
        Slow path: semantic similarity in ChromaDB (only if vector_store provided).
        """
        h = self._hash(title)

        # Fast: check Redis title hash (milliseconds)
        if await self.redis.sismember(SEEN_KEY, h):
            return True

        # Slow: semantic similarity check (only for high-value items)
        if self.vector and text and len(text) > 50:
            similar = self.vector.query(text, n_results=1)
            if similar and similar[0].get("score", 0) >= 0.93:
                return True

        return False

    async def mark_seen(self, title: str):
        """Add title hash to seen set after emitting."""
        h = self._hash(title)
        await self.redis.sadd(SEEN_KEY, h)
        await self.redis.expire(SEEN_KEY, SEEN_TTL)

    async def filter_new(self, items: list[dict]) -> list[dict]:
        """
        Filter a list of signal dicts to only unseen items.
        Marks all returned items as seen.
        """
        new_items = []
        for item in items:
            title = item.get("title", "")
            text  = f"{title} {item.get('summary', '')}"
            if not await self.is_duplicate(title, text):
                new_items.append(item)
                await self.mark_seen(title)
        return new_items
