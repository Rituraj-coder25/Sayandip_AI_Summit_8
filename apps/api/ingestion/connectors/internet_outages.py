"""Section 8 – Internet Outages (Cloudflare Radar, 5-min poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings


class InternetOutagesConnector(BaseConnector):
    SOURCE_NAME = "cloudflare_radar"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 300

    async def fetch(self):
        if not settings.CLOUDFLARE_API_TOKEN:
            return []
        headers = {"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"}
        results: dict[str, object] = {}
        for key, url in [
            ("iqi",       "https://api.cloudflare.com/client/v4/radar/quality/iqi/summary"),
            ("anomalies", "https://api.cloudflare.com/client/v4/radar/traffic/anomalies/locations"),
            ("bgp",       "https://api.cloudflare.com/client/v4/radar/bgp/route-moas/summary"),
        ]:
            try:
                results[key] = await self.fetch_json(url, headers=headers)
            except Exception:
                results[key] = None
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals: list[dict] = []
        # Traffic anomalies
        anomalies = payload.get("anomalies")
        if anomalies and isinstance(anomalies, dict):
            locations = anomalies.get("result", {}).get("locations", [])
            if not locations and isinstance(anomalies.get("result"), list):
                locations = anomalies["result"]
            for loc in locations:
                cc = loc.get("locationCode") or loc.get("clientCountryAlpha2") or "XX"
                drop = float(loc.get("trafficAnomaly") or loc.get("value") or 0)
                if abs(drop) < 30:
                    continue
                severity = min(100, int(abs(drop)))
                signals.append(
                    self.std_signal(
                        id=f"cf-outage-{cc}-{datetime.now(UTC).strftime('%Y%m%dT%H')}",
                        title=f"Internet Outage: {cc} ({abs(drop):.0f}% traffic drop)",
                        summary=f"Cloudflare Radar detected {abs(drop):.0f}% traffic anomaly in {cc}",
                        domain="technology",
                        severity=severity,
                        india_score=20 if cc == "IN" else 5,
                        raw={"country": cc, "traffic_drop_pct": drop, "source": "cloudflare_radar"},
                        tags=["internet", "outage", cc.lower()],
                    )
                )
        return signals
