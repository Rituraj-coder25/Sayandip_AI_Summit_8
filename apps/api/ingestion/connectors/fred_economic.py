"""Section 10c – FRED Economic Data (8 macro series, 1-hour poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings

FRED_SERIES = {
    "GDP":          "GDP",
    "INFLATION":    "CPIAUCSL",
    "FED_RATE":     "FEDFUNDS",
    "UNEMPLOYMENT": "UNRATE",
    "DXY":          "DTWEXBGS",
    "10Y_YIELD":    "DGS10",
    "VIX":          "VIXCLS",
    "WTI_CRUDE":    "DCOILWTICO",
}


class FREDEconomicConnector(BaseConnector):
    SOURCE_NAME = "fred_economic"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        if not settings.FRED_API_KEY:
            return []
        results = {}
        for label, series_id in FRED_SERIES.items():
            url = (
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series_id}&api_key={settings.FRED_API_KEY}"
                f"&limit=5&sort_order=desc&file_type=json"
            )
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
            observations = data.get("observations", [])
            if not observations:
                continue
            latest = observations[0]
            value = latest.get("value", ".")
            if value == ".":
                continue
            date = latest.get("date", "")
            signals.append(
                self.std_signal(
                    id=f"fred-{label}-{date}",
                    title=f"FRED {label}: {value}",
                    summary=f"{FRED_SERIES[label]} series latest value: {value} ({date})",
                    domain="economics",
                    severity=30,
                    india_score=10 if label in ("DXY", "WTI_CRUDE") else 5,
                    url=f"https://fred.stlouisfed.org/series/{FRED_SERIES[label]}",
                    published_at=f"{date}T00:00:00Z" if date else datetime.now(UTC).isoformat(),
                    raw={"series": FRED_SERIES[label], "label": label, "value": value, "date": date},
                    tags=["economics", "fred", label.lower()],
                )
            )
        return signals
