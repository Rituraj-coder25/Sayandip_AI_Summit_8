from datetime import UTC, datetime

from ..base_connector import BaseConnector


class NOAAConnector(BaseConnector):
    SOURCE_NAME = "noaa_weather"
    POLL_INTERVAL_SECONDS = 900
    URL = "https://api.weather.gov/alerts/active"

    async def fetch(self):
        return await self.fetch_json(self.URL)

    async def parse(self, payload):
        features = payload.get("features", [])
        return [
            {
                "id": feature.get("id") or f"noaa-{index}",
                "source_name": self.SOURCE_NAME,
                "title": (feature.get("properties") or {}).get("headline") or "NOAA active alert",
                "summary": (feature.get("properties") or {}).get("description") or "Weather alert",
                "raw_text": " ".join(
                    filter(
                        None,
                        [
                            (feature.get("properties") or {}).get("headline"),
                            (feature.get("properties") or {}).get("description"),
                        ],
                    )
                ),
                "domain": "climate",
                "published_at": (feature.get("properties") or {}).get("sent") or datetime.now(UTC).isoformat(),
                "tags": ["noaa", "weather"],
            }
            for index, feature in enumerate(features[:20])
        ]
