"""Section 9 – GPS Jamming (gpsjam.org H3 hex grid, 1-hour poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector

JAMMING_REGIONS = {
    "Iran-Iraq":        {"lat_range": (29, 38), "lon_range": (44, 56)},
    "Levant":           {"lat_range": (29, 36), "lon_range": (34, 42)},
    "Ukraine-Russia":   {"lat_range": (44, 55), "lon_range": (22, 42)},
    "Baltic":           {"lat_range": (54, 62), "lon_range": (14, 30)},
    "Mediterranean":    {"lat_range": (30, 46), "lon_range": (-5, 36)},
    "Black Sea":        {"lat_range": (40, 47), "lon_range": (28, 41)},
    "Arctic":           {"lat_range": (70, 90), "lon_range": (-180, 180)},
    "Caucasus":         {"lat_range": (38, 44), "lon_range": (38, 51)},
    "Central Asia":     {"lat_range": (36, 48), "lon_range": (55, 80)},
    "Horn of Africa":   {"lat_range": (2, 15),  "lon_range": (40, 52)},
    "Korean Peninsula": {"lat_range": (34, 40), "lon_range": (124, 132)},
    "South China Sea":  {"lat_range": (0, 22),  "lon_range": (105, 125)},
}


def _tag_region(lat: float, lon: float) -> str:
    for name, bounds in JAMMING_REGIONS.items():
        lr = bounds["lat_range"]
        lo = bounds["lon_range"]
        if lr[0] <= lat <= lr[1] and lo[0] <= lon <= lo[1]:
            return name
    return "Other"


class GPSJammingConnector(BaseConnector):
    SOURCE_NAME = "gps_jamming"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        # Try API endpoint first, fall back to about page
        for url in [
            "https://gpsjam.org/api/latest",
            "https://gpsjam.org/about",
        ]:
            try:
                return await self.fetch_json(url)
            except Exception:
                continue
        return []

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        cells = payload if isinstance(payload, list) else payload.get("cells", [])
        signals: list[dict] = []

        try:
            import h3
        except ImportError:
            # h3 not installed — skip
            return []

        for cell in cells:
            h3_index = cell.get("h3_index") or cell.get("hex") or ""
            bad_pct = float(cell.get("bad_percent") or cell.get("bad_pct") or 0)
            total = int(cell.get("total_aircraft") or cell.get("total") or 0)

            if total < 3:
                continue
            if bad_pct <= 2:
                continue

            if bad_pct > 10:
                severity = 75
                level = "HIGH"
            else:
                severity = 45
                level = "MEDIUM"

            try:
                lat, lon = h3.h3_to_geo(h3_index)
            except Exception:
                lat, lon = 0.0, 0.0

            region = _tag_region(lat, lon)

            signals.append(
                self.std_signal(
                    id=f"gps-jam-{h3_index}-{datetime.now(UTC).strftime('%Y%m%d')}",
                    title=f"GPS Jamming: {region} ({level})",
                    summary=f"{bad_pct:.1f}% of {total} aircraft reporting GPS anomalies",
                    domain="defense",
                    severity=severity,
                    india_score=5,
                    raw={
                        "h3_index": h3_index,
                        "bad_percent": bad_pct,
                        "total_aircraft": total,
                        "region": region,
                    },
                    tags=["gps", "jamming", region.lower().replace(" ", "_")],
                    latitude=lat,
                    longitude=lon,
                )
            )
        return signals
