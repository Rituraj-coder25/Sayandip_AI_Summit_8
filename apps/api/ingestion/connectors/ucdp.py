"""UCDP – Uppsala Conflict Data Program (free, no key, 1-hour poll)."""
from __future__ import annotations
from datetime import UTC, datetime
from ..base_connector import BaseConnector

class UCDPConnector(BaseConnector):
    SOURCE_NAME = "ucdp_conflicts"
    POLL_INTERVAL_SECONDS = 3600   # 1 hour — data updates daily, not real-time
    CACHE_TTL_SECONDS = 3600

    GED_URL = "https://ucdpapi.pcr.uu.se/api/gedevents/23.1?pagesize=100&page=1"

    async def fetch(self):
        try:
            return await self.fetch_json(self.GED_URL)
        except Exception:
            return {}

    async def parse(self, payload) -> list[dict]:
        results = payload.get("Result", []) or []
        signals = []
        for event in results[:50]:
            deaths = int(event.get("best", 0) or 0)
            signals.append(self.std_signal(
                id=f"ucdp-{event.get('id')}",
                title=f"UCDP: {event.get('conflict_name', 'Armed conflict event')}",
                summary=(
                    f"{event.get('type_of_violence_label', 'Violence')} in "
                    f"{event.get('country', 'Unknown')}. "
                    f"Deaths: {deaths}. "
                    f"Actors: {event.get('side_a', '')} vs {event.get('side_b', '')}."
                ),
                domain="defense",
                severity=90 if deaths > 100 else 75 if deaths > 10 else 55 if deaths > 0 else 40,
                india_score=30 if any(k in str(event) for k in ["India", "Pakistan", "Kashmir", "Bangladesh", "Myanmar"]) else 5,
                url=f"https://ucdp.uu.se/event/{event.get('id')}",
                published_at=event.get("date_start") or datetime.now(UTC).isoformat(),
                raw=event,
                latitude=_safe_float(event.get("latitude")),
                longitude=_safe_float(event.get("longitude")),
                tags=["ucdp", "conflict", event.get("type_of_violence_label", "").lower().replace(" ", "_")],
            ))
        return signals

def _safe_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
