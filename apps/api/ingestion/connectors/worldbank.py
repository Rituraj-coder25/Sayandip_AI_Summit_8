from datetime import UTC, datetime

from ..base_connector import BaseConnector


class WorldBankConnector(BaseConnector):
    SOURCE_NAME = "worldbank_data"
    POLL_INTERVAL_SECONDS = 21600
    URL = "https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.CD?format=json"

    async def fetch(self):
        return await self.fetch_json(self.URL)

    async def parse(self, payload):
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        items = []
        for row in rows[:5]:
            value = row.get("value")
            if value is None:
                continue
            items.append(
                {
                    "id": f"worldbank-{row.get('date')}",
                    "source_name": self.SOURCE_NAME,
                    "title": f"World Bank India GDP indicator for {row.get('date')}",
                    "summary": f"GDP value recorded at {value}",
                    "raw_text": f"India GDP {row.get('date')} value {value}",
                    "domain": "economics",
                    "published_at": datetime.now(UTC).isoformat(),
                    "tags": ["worldbank", "economics"],
                }
            )
        return items
