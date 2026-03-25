"""Section 16 – Live Stream Catalog (health-check validation, 1-hour poll)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings

LIVE_STREAMS = [
    {"name": "France24 EN",       "url": "https://static.france24.com/live/F24_EN_HI_HLS/live_web.m3u8", "type": "hls", "region": "europe",  "category": "news"},
    {"name": "DW News",           "url": "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8", "type": "hls", "region": "europe",  "category": "news"},
    {"name": "CGTN",              "url": "https://news.cgtn.com/resource/live/english/cgtn-news.m3u8", "type": "hls", "region": "asia",    "category": "news"},
    {"name": "Jerusalem Webcam",  "youtube_id": "oBTYEPCnkO4", "type": "youtube", "region": "mena",  "category": "surveillance", "lat": 31.7767, "lon": 35.2345},
]


class LiveStreamCatalogConnector(BaseConnector):
    SOURCE_NAME = "live_stream_catalog"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        if not settings.LIVE_STREAMS_ENABLED:
            return []
        results = []
        for stream in LIVE_STREAMS:
            status = "unknown"
            url = stream.get("url", "")
            if url:
                try:
                    resp = await self.http.head(url, timeout=10.0)
                    status = "online" if resp.status_code < 400 else "offline"
                except Exception:
                    status = "offline"
            elif stream.get("youtube_id"):
                status = "youtube"  # can't HEAD-check easily
            results.append({**stream, "status": status})
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        # Store full catalog in Redis
        catalog_json = json.dumps(payload, default=str)
        await self.redis.setex("goe:live_streams", 3600, catalog_json)

        # Only emit signals for status changes (offline detection)
        signals = []
        cached_raw = await self.redis.get("goe:cache:live_stream_catalog")
        old_statuses = {}
        if cached_raw:
            try:
                old_data = json.loads(cached_raw)
                old_statuses = {s.get("name"): s.get("status") for s in old_data if isinstance(s, dict) and "name" in s}
            except Exception:
                pass

        for stream in payload:
            name = stream.get("name", "")
            new_status = stream.get("status", "unknown")
            old_status = old_statuses.get(name)
            if old_status and old_status != new_status:
                signals.append(
                    self.std_signal(
                        id=f"stream-{name.replace(' ','_')}-{datetime.now(UTC).strftime('%Y%m%dT%H')}",
                        title=f"Stream Status Change: {name} → {new_status}",
                        summary=f"Live stream '{name}' changed from {old_status} to {new_status}",
                        domain="technology",
                        severity=40 if new_status == "offline" else 20,
                        india_score=10 if stream.get("region") == "india" else 5,
                        raw={"stream": name, "old": old_status, "new": new_status, "region": stream.get("region")},
                        tags=["live_stream", stream.get("region", "unknown")],
                    )
                )
        return signals
