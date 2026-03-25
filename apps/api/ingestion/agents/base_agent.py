"""
Base class for all GOE scraper agents.
Extends the spirit of BaseConnector but for agents that:
- Have stateful session management (browser sessions, WebSocket connections)
- Make AI-directed decisions about what to scrape next
- May run as long-lived async tasks rather than one-shot polls
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("goe.agent")


class BaseAgent(ABC):
    """
    All agents inherit this.
    Key difference from BaseConnector:
    - BaseConnector: fetch once per interval, return list of signals
    - BaseAgent: long-running loop OR smarter session-aware fetching
    Both produce the same std_signal() output format.
    Both are called identically by GOEScheduler.
    """

    AGENT_NAME: str = ""
    POLL_INTERVAL_SECONDS: int = 300
    CACHE_TTL_SECONDS: int = 240
    MAX_SIGNALS_PER_RUN: int = 50    # cap signals per cycle to protect pipeline

    def __init__(self, redis_client: aioredis.Redis, http_client):
        self.redis  = redis_client
        self.http   = http_client
        self.logger = logging.getLogger(f"goe.agent.{self.AGENT_NAME}")

    @abstractmethod
    async def scrape(self) -> list[dict]:
        """
        Core scraping logic. Returns list of std_signal dicts.
        Must NOT swallow exceptions — let them bubble to base run().
        """
        ...

    async def run(self) -> list[dict]:
        """
        Called by GOEScheduler. Mirrors BaseConnector.run() exactly
        so scheduler code is identical for both connectors and agents.
        """
        # Rate limit guard
        last_fetch_raw = await self.redis.get(f"goe:last_fetch:agent:{self.AGENT_NAME}")
        last_fetch = float(last_fetch_raw) if last_fetch_raw else 0.0
        if time.time() - last_fetch < self.POLL_INTERVAL_SECONDS * 0.95:
            # Return cached result without hitting the target site
            cached = await self.redis.get(f"goe:cache:agent:{self.AGENT_NAME}")
            return json.loads(cached) if cached else []

        # Check cache
        cached = await self.redis.get(f"goe:cache:agent:{self.AGENT_NAME}")
        if cached:
            return json.loads(cached)

        t0 = time.time()
        try:
            signals = await self.scrape()
            signals = signals[:self.MAX_SIGNALS_PER_RUN]

            await self.redis.setex(
                f"goe:cache:agent:{self.AGENT_NAME}",
                self.CACHE_TTL_SECONDS,
                json.dumps(signals)
            )
            await self.redis.set(f"goe:last_fetch:agent:{self.AGENT_NAME}", time.time())
            await self.redis.hset(f"goe:agent_health:{self.AGENT_NAME}", mapping={
                "status":       "online",
                "last_success": datetime.now(timezone.utc).isoformat(),
                "items_count":  str(len(signals)),
                "latency_ms":   str(int((time.time() - t0) * 1000)),
            })
            self.logger.info(f"Scraped {len(signals)} signals in {(time.time()-t0):.1f}s")
            return signals

        except Exception as e:
            self.logger.error(f"Scrape failed: {e}", exc_info=True)
            await self.redis.hset(f"goe:agent_health:{self.AGENT_NAME}", mapping={
                "status":     "error",
                "last_error": str(e)[:200],
            })
            # Return stale cache on failure
            stale = await self.redis.get(f"goe:cache:agent:{self.AGENT_NAME}")
            return json.loads(stale) if stale else []

    def std_signal(self, **kwargs) -> dict:
        """
        Identical to BaseConnector.std_signal().
        Produces the exact dict format that GOEIntelligenceEngine.process_signal() expects.
        """
        title = kwargs.get("title", "")
        source_value = f"agent:{self.AGENT_NAME}"
        return {
            "id":           kwargs.get("id", self._make_id(title)),
            "source_name":  source_value,
            "source":       source_value,
            "title":        title,
            "summary":      kwargs.get("summary", ""),
            "domain":       kwargs.get("domain", "geopolitics"),
            "severity":     kwargs.get("severity", 0),
            "india_score":  kwargs.get("india_score", 0),
            "latitude":     kwargs.get("latitude"),
            "longitude":    kwargs.get("longitude"),
            "country_iso":  kwargs.get("country_iso"),
            "source_url":   kwargs.get("url", ""),
            "url":          kwargs.get("url", ""),
            "published_at": kwargs.get("published_at", datetime.now(timezone.utc).isoformat()),
            "raw":          kwargs.get("raw", {}),
            "raw_text":     f"{title} {kwargs.get('summary', '')}".strip(),
            "tags":         kwargs.get("tags", []),
            "translated":   kwargs.get("translated", False),
            "original_lang":kwargs.get("original_lang"),
        }

    @staticmethod
    def _make_id(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:20]
