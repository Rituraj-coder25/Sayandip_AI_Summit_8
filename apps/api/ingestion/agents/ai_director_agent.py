"""
GOE AI Director Agent
=======================
An AI-driven agent loop that:
1. Reads current GOE alert levels from Redis
2. Decides which scraping targets need priority attention right now
3. Directs WorldMonitorAgent and PlaywrightScraperAgent to focus there
4. Summarises what the scraping found and publishes a "director summary" signal

This is what makes the scraper INTELLIGENT rather than dumb cron jobs.
If India Risk Score spikes, the director tells scrapers to focus on India sources.
If a new conflict is detected, it focuses on conflict-zone sources.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from .base_agent import BaseAgent

logger = logging.getLogger("goe.agent.director")


class AIDirectorAgent(BaseAgent):
    """
    Runs every 30 minutes. Reads the current intelligence picture,
    decides what is most important, adjusts scraping priorities.
    """

    AGENT_NAME            = "ai_director"
    POLL_INTERVAL_SECONDS = 1800   # 30 minutes
    CACHE_TTL_SECONDS     = 1700
    MAX_SIGNALS_PER_RUN   = 5

    def __init__(self, redis_client, http_client, llm=None):
        super().__init__(redis_client, http_client)
        self._llm = llm   # LLMClient injected at startup from main.py

    async def scrape(self) -> list[dict]:
        """
        Main director loop:
        1. Read India Risk Score + top recent signals
        2. Ask AI: what should we be watching right now?
        3. Store scraping priorities in Redis for other agents to read
        4. Return a director summary signal
        """
        if not self._llm:
            return []

        # Read current intelligence picture
        risk_raw      = await self.redis.get("goe:india_risk_score_full")
        risk          = json.loads(risk_raw) if risk_raw else {"score": 50}
        signals_today = await self.redis.get("goe:stats:signals_today") or "0"

        # Get top 10 recent signals from Redis
        recent_keys = sorted(await self.redis.keys("goe:signal:*"))[-10:]
        recent      = []
        for key in recent_keys:
            raw = await self.redis.get(key)
            if raw:
                item = json.loads(raw)
                recent.append(f"[{item.get('domain', '?').upper()}|"
                              f"Sev:{item.get('severity', 0)}|"
                              f"India:{item.get('india_score', 0)}] "
                              f"{item.get('title', '')[:100]}")

        # Ask AI director: what should we focus on?
        prompt = f"""You are the GOE News Scraping Director.

Current intelligence picture:
- India Risk Score: {risk.get('score', 50)}/100 ({risk.get('color', 'amber')})
- Signals processed today: {signals_today}
- Top recent signals:
{chr(10).join(recent) or "None yet."}

Based on this, decide:
1. Which domains need the most attention RIGHT NOW? (rank: geopolitics/economics/defense/technology/climate/society)
2. Which specific regions/countries should scrapers focus on? (list up to 4)
3. Any specific topics to watch for in the next 30 minutes?
4. Overall scraping priority: HIGH / MEDIUM / LOW

Return JSON only:
{{
  "priority_domains": ["defense", "geopolitics"],
  "focus_regions": ["South Asia", "Middle East"],
  "watch_topics": ["LOC", "Iran nuclear", "NIFTY"],
  "scraping_priority": "HIGH",
  "reasoning": "one sentence"
}}"""

        result = await self._llm.complete(prompt, max_tokens=300, prefer_fast=True)
        if not result:
            return []

        try:
            raw = result.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            directive = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return []

        # Store directive in Redis for other agents to read
        await self.redis.setex(
            "goe:agent:director_directive",
            1800,
            json.dumps(directive)
        )

        # Publish as a signal (shows in admin panel under agent status)
        return [self.std_signal(
            id=f"director_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            title=f"[Director] Priority: {directive.get('scraping_priority', '?')} — Focus: {', '.join(directive.get('priority_domains', [])[:2])}",
            summary=directive.get("reasoning", "") + f" | Watch: {', '.join(directive.get('watch_topics', [])[:3])}",
            domain="geopolitics",
            severity=5,
            india_score=50,
            tags=["agent-director", "internal"],
            raw=directive,
        )]
