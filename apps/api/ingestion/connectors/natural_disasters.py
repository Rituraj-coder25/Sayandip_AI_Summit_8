"""Section 4 – Natural Disasters (USGS + GDACS + NASA EONET, 5-min poll)."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import feedparser

from ..base_connector import BaseConnector


def _haversine_key(lat: float, lon: float, precision: float = 0.1) -> str:
    return f"{round(lat / precision) * precision:.1f}_{round(lon / precision) * precision:.1f}"


class NaturalDisasterConnector(BaseConnector):
    SOURCE_NAME = "natural_disasters"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 300

    async def fetch(self):
        results: dict[str, object] = {}
        # USGS M4.5+
        try:
            results["usgs"] = await self.fetch_json(
                "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_hour.geojson"
            )
        except Exception:
            results["usgs"] = None
        # GDACS RSS
        try:
            results["gdacs"] = await self.fetch_text("https://www.gdacs.org/xml/rss.xml")
        except Exception:
            results["gdacs"] = None
        # NASA EONET
        try:
            results["eonet"] = await self.fetch_json(
                "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30"
            )
        except Exception:
            results["eonet"] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals: list[dict] = []
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        dedup_key = f"goe:disaster_dedup:{today}"
        seen: set[str] = set()

        # Helper to add if not duplicate
        async def _add(source_priority: int, sig: dict, lat: float, lon: float):
            hk = _haversine_key(lat, lon)
            member = f"{hk}:{today}"
            if member in seen:
                return
            already = await self.redis.sismember(dedup_key, member) if hasattr(self.redis, 'sismember') else False
            if already:
                return
            seen.add(member)
            if hasattr(self.redis, 'sadd'):
                await self.redis.sadd(dedup_key, member)
                await self.redis.expire(dedup_key, 86400)
            signals.append(sig)

        # ──── USGS ────
        if payload.get("usgs"):
            for feature in payload["usgs"].get("features", [])[:30]:
                props = feature.get("properties", {})
                coords = feature.get("geometry", {}).get("coordinates", [0, 0])
                mag = float(props.get("mag") or 0)
                sig = self.std_signal(
                    id=f"usgs-{feature.get('id')}",
                    title=props.get("title") or "USGS Earthquake",
                    summary=f"Magnitude {mag} earthquake",
                    domain="climate",
                    severity=int(min(100, max(20, mag * 12))),
                    india_score=10,
                    url=props.get("url", ""),
                    published_at=datetime.fromtimestamp(
                        (props.get("time") or 0) / 1000, tz=UTC
                    ).isoformat() if props.get("time") else datetime.now(UTC).isoformat(),
                    raw={"source": "usgs", "magnitude": mag},
                    tags=["earthquake", "usgs"],
                    latitude=coords[1] if len(coords) > 1 else None,
                    longitude=coords[0] if len(coords) > 0 else None,
                )
                lat = coords[1] if len(coords) > 1 else 0
                lon = coords[0] if len(coords) > 0 else 0
                await _add(1, sig, lat, lon)

        # ──── GDACS ────
        if payload.get("gdacs"):
            parsed = feedparser.parse(payload["gdacs"])
            for entry in parsed.entries[:30]:
                title = (entry.get("title") or "GDACS Alert").strip()
                summary_text = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                # Determine severity from title
                title_lower = title.lower()
                if "red" in title_lower:
                    severity = 85
                elif "orange" in title_lower:
                    severity = 65
                else:
                    continue  # Skip green/low
                lat = float(entry.get("geo_lat", entry.get("gdacs_lat", 0)) or 0)
                lon = float(entry.get("geo_long", entry.get("gdacs_long", 0)) or 0)
                sig = self.std_signal(
                    id=f"gdacs-{entry.get('id', title[:30])}",
                    title=title,
                    summary=summary_text[:500],
                    domain="climate",
                    severity=severity,
                    india_score=10,
                    url=entry.get("link", ""),
                    published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                    raw={"source": "gdacs"},
                    tags=["disaster", "gdacs"],
                    latitude=lat,
                    longitude=lon,
                )
                await _add(2, sig, lat, lon)

        # ──── NASA EONET ────
        if payload.get("eonet"):
            cutoff_48h = datetime.now(UTC) - timedelta(hours=48)
            for event in payload["eonet"].get("events", [])[:30]:
                categories = [c.get("title", "").lower() for c in event.get("categories", [])]
                # Skip earthquakes (USGS is better)
                if "earthquakes" in categories:
                    continue
                geo_list = event.get("geometry", [])
                if not geo_list:
                    continue
                latest = geo_list[-1]
                coords = latest.get("coordinates", [0, 0])
                lat = coords[1] if len(coords) > 1 else 0
                lon = coords[0] if len(coords) > 0 else 0
                sig = self.std_signal(
                    id=f"eonet-{event.get('id')}",
                    title=event.get("title", "EONET Event"),
                    summary=f"NASA EONET event: {', '.join(categories)}",
                    domain="climate",
                    severity=50,
                    india_score=5,
                    url=event.get("link") or event.get("sources", [{}])[0].get("url", "") if event.get("sources") else "",
                    raw={"source": "eonet", "categories": categories},
                    tags=["disaster", "eonet"] + categories,
                    latitude=lat,
                    longitude=lon,
                )
                await _add(3, sig, lat, lon)

        return signals
