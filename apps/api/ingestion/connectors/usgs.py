from datetime import UTC, datetime

from ..base_connector import BaseConnector


class USGSConnector(BaseConnector):
    SOURCE_NAME = "usgs_earthquakes"
    POLL_INTERVAL_SECONDS = 300
    URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"

    async def fetch(self):
        return await self.fetch_json(self.URL)

    async def parse(self, payload):
        items = []
        for feature in payload.get("features", [])[:30]:
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            coords = geometry.get("coordinates", [None, None])
            title = props.get("title") or "USGS Earthquake"
            summary = f"Magnitude {props.get('mag')} earthquake reported by USGS."
            items.append(
                {
                    "id": str(feature.get("id")),
                    "external_id": str(feature.get("id")),
                    "source_name": self.SOURCE_NAME,
                    "title": title,
                    "summary": summary,
                    "raw_text": f"{title}. {summary}",
                    "domain": "climate",
                    "severity": int(min(100, max(20, float(props.get("mag") or 0) * 12))),
                    "latitude": coords[1] if len(coords) > 1 else None,
                    "longitude": coords[0] if len(coords) > 0 else None,
                    "source_url": props.get("url"),
                    "published_at": datetime.fromtimestamp((props.get("time") or 0) / 1000, tz=UTC).isoformat() if props.get("time") else datetime.now(UTC).isoformat(),
                    "tags": ["earthquake", "usgs"],
                }
            )
        return items
