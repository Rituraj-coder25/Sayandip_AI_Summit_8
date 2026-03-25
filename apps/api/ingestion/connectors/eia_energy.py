"""Section 10d – EIA Energy Data (WTI + Natural Gas, 1-hour poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings


class EIAEnergyConnector(BaseConnector):
    SOURCE_NAME = "eia_energy"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        if not settings.EIA_API_KEY:
            return []
        results = {}
        key = settings.EIA_API_KEY
        endpoints = {
            "wti": (
                f"https://api.eia.gov/v2/petroleum/pri/spt/data/"
                f"?api_key={key}&data[]=value&frequency=daily"
                f"&sort[0][column]=period&sort[0][direction]=desc&length=5"
            ),
            "natgas": (
                f"https://api.eia.gov/v2/natural-gas/pri/sum/data/"
                f"?api_key={key}&data[]=value&frequency=monthly&length=3"
            ),
        }
        for label, url in endpoints.items():
            try:
                results[label] = await self.fetch_json(url)
            except Exception:
                results[label] = None
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals = []
        for label, data in payload.items():
            if not data:
                continue
            rows = data.get("response", {}).get("data", [])
            if not rows:
                continue
            latest = rows[0]
            value = latest.get("value", "")
            period = latest.get("period", "")
            name = "WTI Crude Oil" if label == "wti" else "Natural Gas"
            signals.append(
                self.std_signal(
                    id=f"eia-{label}-{period}",
                    title=f"EIA {name}: ${value}",
                    summary=f"{name} price: ${value} ({period})",
                    domain="economics",
                    severity=30,
                    india_score=10,
                    url="https://www.eia.gov/petroleum/",
                    published_at=f"{period}T00:00:00Z" if period else datetime.now(UTC).isoformat(),
                    raw={"label": label, "value": value, "period": period},
                    tags=["energy", "eia", label],
                )
            )
        return signals
