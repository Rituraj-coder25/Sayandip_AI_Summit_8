"""Section 10f – BIS Central Bank Data (daily poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings


class BISDataConnector(BaseConnector):
    SOURCE_NAME = "bis_central_banks"
    POLL_INTERVAL_SECONDS = 86400
    CACHE_TTL_SECONDS = 86400

    async def fetch(self):
        if not settings.BIS_FEEDS_ENABLED:
            return []
        results = {}
        for key, url in [
            ("policy_rates", "https://data.bis.org/topics/SPE/BIS,WS_SPE,1.0/all?format=json"),
            ("reer",         "https://data.bis.org/topics/EER/BIS,WS_EER,1.0/all?format=json"),
        ]:
            try:
                results[key] = await self.fetch_json(url)
            except Exception:
                results[key] = None
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals = []
        now = datetime.now(UTC).isoformat()
        for dataset_name, data in payload.items():
            if not data:
                continue
            # BIS SDMX-JSON structure
            datasets = data.get("dataSets", [])
            for ds in datasets[:5]:
                obs = ds.get("observations", ds.get("series", {}))
                if isinstance(obs, dict):
                    for key, values in list(obs.items())[:20]:
                        signals.append(
                            self.std_signal(
                                id=f"bis-{dataset_name}-{key[:40]}",
                                title=f"BIS {dataset_name}: {key[:60]}",
                                summary=f"BIS {dataset_name} data point",
                                domain="economics",
                                severity=25,
                                india_score=10 if "IN" in key else 5,
                                url="https://data.bis.org/",
                                published_at=now,
                                raw={"dataset": dataset_name, "key": key},
                                tags=["economics", "bis", dataset_name],
                            )
                        )
        return signals
