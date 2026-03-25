"""
Playwright News Scraper Agent
==============================
Scrapes JavaScript-rendered news pages that block RSS feeds.
Targets: live blog pages, breaking news tickers, JS-only news sites.

Runs on a longer interval (15 min) since Playwright is expensive.
Only scrapes HIGH-PRIORITY targets defined in SCRAPE_TARGETS below.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

from .base_agent import BaseAgent
from .utils.deduplicator import AgentDeduplicator
from .utils.rate_limiter import DomainRateLimiter
from .utils.html_extractor import extract_article_text, extract_headline, extract_meta

logger = logging.getLogger("goe.agent.playwright")

# Targets that justify Playwright (can't be scraped with plain HTTP)
# Format: {name, url, domain, selectors, priority}
SCRAPE_TARGETS = [
    {
        "name":      "Reuters Breaking News",
        "url":       "https://www.reuters.com/news/archive/",
        "domain":    "geopolitics",
        "selector":  "article.story-card, .media-story-card",
        "priority":  1,
    },
    {
        "name":      "BBC News Live",
        "url":       "https://www.bbc.com/news/live",
        "domain":    "geopolitics",
        "selector":  ".lx-stream-post, .post-article, [data-testid='live-post']",
        "priority":  1,
    },
    {
        "name":      "ISW Daily Assessment",
        "url":       "https://www.understandingwar.org/backgrounder/ukraine-conflict-updates",
        "domain":    "defense",
        "selector":  ".field-item, article, .node__content",
        "priority":  2,
    },
    {
        "name":      "Liveuamap Global",
        "url":       "https://liveuamap.com/",
        "domain":    "geopolitics",
        "selector":  ".event_timeline_item, .event-post, [data-event-id]",
        "priority":  1,
    },
    {
        "name":      "NDTV India Breaking",
        "url":       "https://www.ndtv.com/latest/india",
        "domain":    "geopolitics",
        "selector":  ".news_item, .nstory-main-a, .nstory-list",
        "priority":  2,
    },
    {
        "name":      "Economic Times Markets",
        "url":       "https://economictimes.indiatimes.com/markets",
        "domain":    "economics",
        "selector":  ".eachStory, .story-item, .articlelist",
        "priority":  2,
    },
]


class PlaywrightScraperAgent(BaseAgent):

    AGENT_NAME            = "playwright_news_scraper"
    POLL_INTERVAL_SECONDS = 900    # 15 minutes — Playwright is expensive
    CACHE_TTL_SECONDS     = 850
    MAX_SIGNALS_PER_RUN   = 30

    def __init__(self, redis_client, http_client):
        super().__init__(redis_client, http_client)
        self._dedup        = AgentDeduplicator(redis_client)
        self._rate_limiter = DomainRateLimiter(redis_client)

    async def scrape(self) -> list[dict]:
        """Scrape all PRIORITY 1 targets, rotate through PRIORITY 2."""
        targets  = [t for t in SCRAPE_TARGETS if t["priority"] == 1]
        # Rotate priority 2 — scrape a different one each run
        p2       = [t for t in SCRAPE_TARGETS if t["priority"] == 2]
        if p2:
            run_key = await self.redis.get("goe:agent:pw_p2_idx") or b"0"
            idx     = int(run_key) % len(p2)
            targets.append(p2[idx])
            await self.redis.set("goe:agent:pw_p2_idx", idx + 1)

        signals = []
        for target in targets:
            try:
                target_signals = await self._scrape_target(target)
                signals.extend(target_signals)
            except Exception as e:
                self.logger.warning(f"Failed to scrape {target['name']}: {e}")

        return await self._dedup.filter_new(signals)

    async def _scrape_target(self, target: dict) -> list[dict]:
        """Scrape one target with Playwright."""
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async

        domain_str = urlparse(target["url"]).netloc
        await self._rate_limiter.wait_if_needed(domain_str)

        signals = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            await stealth_async(page)

            try:
                await page.goto(target["url"], timeout=15000,
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Extract items using target's CSS selector
                items = await page.query_selector_all(target["selector"])
                self.logger.debug(f"{target['name']}: found {len(items)} items")

                for item in items[:15]:
                    try:
                        text = (await item.inner_text()).strip()
                        if len(text) < 15:
                            continue

                        # Try to extract a link
                        link_el = await item.query_selector("a")
                        url = ""
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                url = urljoin(target["url"], href)

                        title   = text[:200]
                        summary = text[:600]

                        signals.append(self.std_signal(
                            title=f"[{target['name']}] {title}",
                            summary=summary,
                            domain=target["domain"],
                            severity=30,
                            india_score=self._guess_india_score(target, text),
                            url=url or target["url"],
                            tags=["playwright-scraped", target["name"].lower().replace(" ", "-")],
                        ))
                    except Exception:
                        continue

            finally:
                await browser.close()

        return signals

    def _guess_india_score(self, target: dict, text: str) -> int:
        """Quick India relevance estimate based on target and text."""
        base  = 60 if "india" in target["name"].lower() else 10
        text  = text.lower()
        extra = 25 if any(k in text for k in
                          ["india", "modi", "delhi", "pakistan", "china border"]) else 0
        return min(100, base + extra)
