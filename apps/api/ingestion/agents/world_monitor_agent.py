"""
GOE World Monitor Agent
========================
Scrapes world-monitor.com for live intelligence signals.

Architecture:
- world-monitor.com loads its "signal chain" via WebSocket connection
- The site also exposes specific data endpoints used by its internal app
- This agent uses THREE complementary strategies:
  1. WebSocket listener: connects to world-monitor.com live feed WebSocket
  2. HTTP polling: fetches the site's internal API endpoints (DEFCON, earthquakes, markets)
  3. Playwright fallback: if endpoints change, render the page and extract live feed DOM

All three are tried in order. If WebSocket is available, it's the primary source.
HTTP polling runs as backup. Playwright runs only if both fail.

Rate limiting: max 1 WebSocket connection, requests staggered ≥3s.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .base_agent import BaseAgent
from .utils.deduplicator import AgentDeduplicator
from .utils.rate_limiter import DomainRateLimiter
from .utils.html_extractor import extract_article_text, extract_headline

logger = logging.getLogger("goe.agent.world_monitor")

WORLD_MONITOR_BASE = "https://world-monitor.com"

# Known world-monitor.com internal endpoints
# (discovered by inspecting the site's network requests)
WM_ENDPOINTS = {
    "signals":    "https://world-monitor.com/api/signals",
    "defcon":     "https://world-monitor.com/api/defcon",
    "outbreaks":  "https://world-monitor.com/api/outbreaks",
    "markets":    "https://world-monitor.com/api/markets",
    "seismic":    "https://world-monitor.com/api/seismic",
}

# WebSocket endpoint — discovered via browser DevTools on world-monitor.com
WM_WEBSOCKET_URL = "wss://world-monitor.com/ws"

# If the WS or API endpoints do not resolve, fall back to scraping these
# page sections from the rendered HTML
WM_SCRAPE_SELECTORS = {
    "signal_items":  ".signal-item, .chain-item, [data-signal], .live-event",
    "market_ticker": ".ticker-item, .market-row, [data-market]",
    "defcon_level":  ".defcon, [data-defcon], #defcon-level",
    "outbreak_item": ".outbreak, [data-outbreak], .disease-alert",
}

# Domain routing: world-monitor signal types → GOE domains
WM_DOMAIN_MAP = {
    "stocks":    "economics",
    "markets":   "economics",
    "defcon":    "defense",
    "outbreaks": "society",
    "seismic":   "climate",
    "conflict":  "geopolitics",
    "military":  "defense",
    "cyber":     "technology",
    "tv":        "geopolitics",
    "cameras":   "geopolitics",
    "default":   "geopolitics",
}


class WorldMonitorAgent(BaseAgent):
    """
    Scrapes world-monitor.com live signals and converts them to GOE std_signal format.
    Registered in GOEScheduler as a regular connector.
    """

    AGENT_NAME            = "world_monitor_live"
    POLL_INTERVAL_SECONDS = 180    # 3 minutes
    CACHE_TTL_SECONDS     = 170
    MAX_SIGNALS_PER_RUN   = 40

    def __init__(self, redis_client, http_client):
        super().__init__(redis_client, http_client)
        self._dedup        = AgentDeduplicator(redis_client)
        self._rate_limiter = DomainRateLimiter(redis_client)
        self._ws_task      = None    # background WS listener task
        self._ws_buffer    = []      # signals received via WS, drained each poll

    # ── Main scrape entry point ───────────────────────────────────────────
    async def scrape(self) -> list[dict]:
        """
        Try each strategy in order. Combine results. Deduplicate. Return.
        Strategy 1: Drain WebSocket buffer (if WS is running)
        Strategy 2: HTTP API polling (main reliable path)
        Strategy 3: Playwright HTML scraping (fallback)
        """
        signals = []

        # Strategy 1: WebSocket buffer
        ws_signals = self._drain_ws_buffer()
        signals.extend(ws_signals)

        # Strategy 2: HTTP API endpoints
        await self._rate_limiter.wait_if_needed("world-monitor.com")
        http_signals = await self._fetch_http_endpoints()
        signals.extend(http_signals)

        # Strategy 3: If HTTP gave nothing, try Playwright
        if not signals:
            self.logger.info("HTTP endpoints returned nothing — trying Playwright")
            try:
                pw_signals = await self._scrape_with_playwright()
                signals.extend(pw_signals)
            except Exception as e:
                self.logger.warning(f"Playwright scrape failed: {e}")

        # Deduplicate against existing RSS cache
        new_signals = await self._dedup.filter_new(signals)
        self.logger.info(f"World Monitor: {len(signals)} scraped → {len(new_signals)} new")
        return new_signals

    # ── Strategy 2: HTTP API polling ──────────────────────────────────────
    async def _fetch_http_endpoints(self) -> list[dict]:
        """
        Try each known world-monitor.com API endpoint.
        If an endpoint returns 404/403, log it and skip — the site may have changed.
        """
        signals = []
        headers = {
            "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer":     WORLD_MONITOR_BASE,
            "Accept":      "application/json, text/plain, */*",
            "Origin":      WORLD_MONITOR_BASE,
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for endpoint_name, url in WM_ENDPOINTS.items():
                try:
                    await self._rate_limiter.wait_if_needed("world-monitor.com")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            ct = resp.content_type or ""
                            if "json" in ct:
                                data = await resp.json(content_type=None)
                                parsed = self._parse_endpoint(endpoint_name, data)
                                signals.extend(parsed)
                            else:
                                html = await resp.text()
                                parsed = self._parse_html_endpoint(endpoint_name, html)
                                signals.extend(parsed)
                        elif resp.status in (403, 404, 429):
                            self.logger.debug(f"WM endpoint {endpoint_name} returned {resp.status}")
                except asyncio.TimeoutError:
                    self.logger.debug(f"WM endpoint {endpoint_name} timed out")
                except Exception as e:
                    self.logger.debug(f"WM endpoint {endpoint_name} error: {e}")

        return signals

    def _parse_endpoint(self, endpoint_name: str, data: Any) -> list[dict]:
        """
        Parse JSON response from a world-monitor endpoint.
        world-monitor.com signals follow a structure like:
        {signals: [{type, title, description, severity, lat, lon, timestamp}]}
        OR
        [{id, message, category, level, location}]
        """
        signals = []
        domain  = WM_DOMAIN_MAP.get(endpoint_name, "geopolitics")

        # Handle both list and dict response shapes
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("signals", "data", "items", "events", "alerts", "results"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            if not items and "level" in data:
                # DEFCON response: {level: 3, description: "..."}
                items = [data]

        for item in items[:20]:
            if not isinstance(item, dict):
                continue

            # Extract title — try multiple possible field names
            title = (
                item.get("title") or
                item.get("message") or
                item.get("description") or
                item.get("headline") or
                item.get("text") or
                ""
            )
            if not title or len(str(title)) < 5:
                continue
            title = str(title)[:300]

            # Extract summary
            summary = (
                item.get("summary") or
                item.get("description") or
                item.get("body") or
                item.get("detail") or
                ""
            )[:600]

            # DEFCON special handling
            if endpoint_name == "defcon" and "level" in item:
                level = item.get("level", 5)
                title = f"DEFCON Level: {level}"
                summary = item.get("description", f"US Defense Condition {level}")
                severity = max(0, min(100, (6 - int(level)) * 20))
                signals.append(self.std_signal(
                    id=f"wm_defcon_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    title=title, summary=summary,
                    domain="defense", severity=severity, india_score=40,
                    raw=item, tags=["defcon", "world-monitor", "usa-nuclear"]
                ))
                continue

            # Standard signal
            lat       = self._extract_float(item, ["lat", "latitude", "geo_lat"])
            lon       = self._extract_float(item, ["lon", "lng", "longitude", "geo_lon"])
            severity  = self._extract_severity(item)
            india_sc  = self._compute_india_score(title, summary, lat, lon)
            sig_domain = WM_DOMAIN_MAP.get(
                (item.get("type") or item.get("category") or endpoint_name or "").lower(),
                domain
            )
            ts = self._extract_timestamp(item)

            signals.append(self.std_signal(
                id=f"wm_{endpoint_name}_{self._make_id(title)}",
                title=f"[World Monitor] {title}",
                summary=summary,
                domain=sig_domain,
                severity=severity,
                india_score=india_sc,
                latitude=lat,
                longitude=lon,
                url=WORLD_MONITOR_BASE,
                published_at=ts,
                raw={**item, "_wm_endpoint": endpoint_name},
                tags=["world-monitor", endpoint_name],
            ))

        return signals

    def _parse_html_endpoint(self, endpoint_name: str, html: str) -> list[dict]:
        """Parse HTML response (for endpoints that return HTML instead of JSON)."""
        from bs4 import BeautifulSoup
        soup    = BeautifulSoup(html, "lxml")
        signals = []
        domain  = WM_DOMAIN_MAP.get(endpoint_name, "geopolitics")

        for sel in WM_SCRAPE_SELECTORS.get("signal_items", "").split(", "):
            items = soup.select(sel)
            for item in items[:10]:
                text = item.get_text(strip=True)[:300]
                if len(text) < 10:
                    continue
                signals.append(self.std_signal(
                    title=f"[WM {endpoint_name}] {text[:100]}",
                    summary=text,
                    domain=domain, severity=30, india_score=15,
                    url=WORLD_MONITOR_BASE,
                    tags=["world-monitor", endpoint_name, "html-scraped"],
                ))

        return signals

    # ── Strategy 3: Playwright browser scrape ────────────────────────────
    async def _scrape_with_playwright(self) -> list[dict]:
        """
        Render world-monitor.com in a headless browser.
        Waits for the signal chain to load (JavaScript rendered).
        Extracts signal items from the DOM.
        Uses playwright-stealth to avoid bot detection.
        """
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async

        signals = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            await stealth_async(page)

            try:
                # Intercept API responses while loading the page
                api_responses = []

                async def handle_response(response):
                    if "api" in response.url and response.status == 200:
                        try:
                            body = await response.json()
                            api_responses.append({
                                "url": response.url,
                                "data": body
                            })
                        except Exception:
                            pass

                page.on("response", handle_response)

                await page.goto(WORLD_MONITOR_BASE, timeout=20000,
                                wait_until="networkidle")
                await page.wait_for_timeout(3000)   # let JS render signal chain

                # Extract signals from DOM
                for sel in WM_SCRAPE_SELECTORS["signal_items"].split(", "):
                    items = await page.query_selector_all(sel)
                    for item in items[:20]:
                        text = await item.inner_text()
                        text = text.strip()[:300]
                        if len(text) < 10:
                            continue
                        signals.append(self.std_signal(
                            title=f"[WM Live] {text[:100]}",
                            summary=text,
                            domain="geopolitics", severity=25, india_score=15,
                            url=WORLD_MONITOR_BASE,
                            tags=["world-monitor", "playwright", "dom-scraped"],
                        ))

                # Also parse any intercepted API responses
                for api_resp in api_responses:
                    ep = api_resp["url"].split("/")[-1]
                    parsed = self._parse_endpoint(ep, api_resp["data"])
                    signals.extend(parsed)

            finally:
                await browser.close()

        return signals

    # ── WebSocket listener ────────────────────────────────────────────────
    async def start_ws_listener(self):
        """
        Long-running WebSocket connection to world-monitor.com.
        Runs as a background asyncio task.
        Signals received are buffered in self._ws_buffer.
        The main scrape() call drains this buffer.

        Start this once at agent startup:
        asyncio.create_task(agent.start_ws_listener())
        """
        import websockets

        while True:
            try:
                self.logger.info(f"Connecting to WM WebSocket: {WM_WEBSOCKET_URL}")
                async with websockets.connect(
                    WM_WEBSOCKET_URL,
                    extra_headers={
                        "Origin":     WORLD_MONITOR_BASE,
                        "User-Agent": "Mozilla/5.0",
                    },
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self.logger.info("WM WebSocket connected")
                    await self.redis.hset(f"goe:agent_health:{self.AGENT_NAME}", mapping={
                        "ws_status": "connected"
                    })
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            sigs = self._parse_ws_message(data)
                            self._ws_buffer.extend(sigs)
                            # Cap buffer at 100 items
                            if len(self._ws_buffer) > 100:
                                self._ws_buffer = self._ws_buffer[-100:]
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            self.logger.debug(f"WS message parse error: {e}")

            except Exception as e:
                self.logger.warning(f"WM WebSocket disconnected: {e}. Retry in 30s.")
                await self.redis.hset(f"goe:agent_health:{self.AGENT_NAME}", mapping={
                    "ws_status": f"disconnected: {str(e)[:80]}"
                })
                await asyncio.sleep(30)   # wait before reconnect

    def _parse_ws_message(self, data: dict) -> list[dict]:
        """Parse a raw WebSocket message into std_signal format."""
        signals = []
        event   = data.get("type") or data.get("event", "")
        payload = data.get("payload") or data.get("data") or data

        if not isinstance(payload, dict):
            return []

        title = payload.get("title") or payload.get("message", "")
        if not title:
            return []

        domain = WM_DOMAIN_MAP.get((payload.get("category", "")).lower(), "geopolitics")
        signals.append(self.std_signal(
            id=f"wm_ws_{self._make_id(str(title) + str(datetime.now().minute))}",
            title=f"[WM Live] {str(title)[:200]}",
            summary=str(payload.get("description", payload.get("body", ""))),
            domain=domain,
            severity=self._extract_severity(payload),
            india_score=15,
            url=WORLD_MONITOR_BASE,
            raw=payload,
            tags=["world-monitor", "websocket", "live"],
        ))
        return signals

    def _drain_ws_buffer(self) -> list[dict]:
        """Return and clear the WebSocket buffer."""
        sigs = self._ws_buffer.copy()
        self._ws_buffer.clear()
        return sigs

    # ── Helpers ───────────────────────────────────────────────────────────
    def _extract_float(self, item: dict, keys: list[str]) -> float | None:
        for k in keys:
            v = item.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    def _extract_severity(self, item: dict) -> int:
        for key in ("severity", "level", "magnitude", "intensity", "priority"):
            v = item.get(key)
            if v is not None:
                try:
                    f = float(v)
                    if f <= 5:
                        return int(f * 18)
                    return min(100, int(f))
                except (TypeError, ValueError):
                    pass
        return 25

    def _extract_timestamp(self, item: dict) -> str:
        for key in ("timestamp", "time", "date", "created_at", "published_at", "datetime"):
            v = item.get(key)
            if v:
                try:
                    return datetime.fromisoformat(
                        str(v).replace("Z", "+00:00")
                    ).isoformat()
                except Exception:
                    pass
        return datetime.now(timezone.utc).isoformat()

    def _compute_india_score(self, title: str, summary: str, lat, lon) -> int:
        """Simple India relevance scoring for world-monitor signals."""
        text  = (title + " " + summary).lower()
        score = 10
        india_kw = ["india", "indian", "pakistan", "china", "loc", "lac", "kashmir",
                    "delhi", "mumbai", "isro", "drdo", "rbi", "nifty", "sensex", "rupee"]
        for kw in india_kw:
            if kw in text:
                score += 20
                break
        if lat and lon:
            if 8 <= lat <= 37 and 68 <= lon <= 97:
                score += 40
            elif -10 <= lat <= 50 and 50 <= lon <= 110:
                score += 15
        return min(100, score)
