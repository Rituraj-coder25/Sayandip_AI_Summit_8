"""
Per-domain rate limiter.
world-monitor.com gets max 1 request every 3 seconds.
News sites get max 1 request per 10 seconds.
This is stored in Redis so it persists across agent restarts.
"""
import asyncio
import time
import logging

import redis.asyncio as aioredis

logger = logging.getLogger("goe.agent.ratelimit")

# Minimum seconds between requests to each domain
DOMAIN_LIMITS = {
    "world-monitor.com":   3,    # live intelligence site — be respectful
    "nytimes.com":         10,
    "bloomberg.com":       10,
    "ft.com":              10,
    "washingtonpost.com":  10,
    "wsj.com":             10,
    "reuters.com":         5,
    "bbc.com":             5,
    "theguardian.com":     5,
    "default":             8,    # any other domain
}


class DomainRateLimiter:

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    def _key(self, domain: str) -> str:
        return f"goe:ratelimit:{domain}"

    def _limit(self, domain: str) -> int:
        for d, limit in DOMAIN_LIMITS.items():
            if d in domain:
                return limit
        return DOMAIN_LIMITS["default"]

    async def wait_if_needed(self, domain: str):
        """
        Check last request time for domain.
        If too soon, sleep the remaining time.
        Then record this request.
        """
        key      = self._key(domain)
        limit    = self._limit(domain)
        last_raw = await self.redis.get(key)
        last     = float(last_raw) if last_raw else 0.0
        elapsed  = time.time() - last
        if elapsed < limit:
            wait = limit - elapsed
            logger.debug(f"Rate limit: waiting {wait:.1f}s for {domain}")
            await asyncio.sleep(wait)
        await self.redis.set(key, time.time(), ex=3600)

    async def can_proceed(self, domain: str) -> bool:
        """Non-blocking check — returns True if enough time has passed."""
        key      = self._key(domain)
        limit    = self._limit(domain)
        last_raw = await self.redis.get(key)
        last     = float(last_raw) if last_raw else 0.0
        return (time.time() - last) >= limit
