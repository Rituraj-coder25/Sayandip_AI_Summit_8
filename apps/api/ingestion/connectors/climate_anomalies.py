"""Section 6 – Climate Anomaly Detection (Open-Meteo ERA5, 1-hour poll)."""
from __future__ import annotations

from datetime import UTC, datetime
import statistics

from ..base_connector import BaseConnector

CLIMATE_ZONES = [
    {"name": "Ukraine-Russia Front",    "lat": 48.5,  "lon": 37.5},
    {"name": "Middle East",             "lat": 32.0,  "lon": 44.0},
    {"name": "Sahel Belt",              "lat": 13.0,  "lon": 12.0},
    {"name": "Horn of Africa",          "lat": 5.0,   "lon": 42.0},
    {"name": "South Asia",              "lat": 25.0,  "lon": 80.0},
    {"name": "Indo-Gangetic Plain",     "lat": 28.0,  "lon": 77.0},
    {"name": "Southeast Asia",          "lat": 15.0,  "lon": 105.0},
    {"name": "Amazon Basin",            "lat": -5.0,  "lon": -60.0},
    {"name": "Australia Outback",       "lat": -25.0, "lon": 134.0},
    {"name": "California",              "lat": 37.0,  "lon": -119.0},
    {"name": "Central Asia",            "lat": 42.0,  "lon": 63.0},
    {"name": "North India",             "lat": 30.0,  "lon": 76.0},
    {"name": "East Africa Rift",        "lat": -1.0,  "lon": 37.0},
    {"name": "Persian Gulf",            "lat": 25.5,  "lon": 51.0},
    {"name": "Korean Peninsula",        "lat": 37.5,  "lon": 127.0},
]


class ClimateAnomalyConnector(BaseConnector):
    SOURCE_NAME = "climate_anomalies"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        results = []
        for zone in CLIMATE_ZONES:
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={zone['lat']}&longitude={zone['lon']}"
                f"&daily=temperature_2m_max,precipitation_sum"
                f"&past_days=30&forecast_days=1&timezone=UTC"
            )
            try:
                data = await self.fetch_json(url)
                results.append({"zone": zone, "data": data})
            except Exception:
                results.append({"zone": zone, "data": None})
        return results

    async def parse(self, payload) -> list[dict]:
        signals: list[dict] = []
        for item in payload:
            zone = item["zone"]
            data = item.get("data")
            if not data:
                continue
            daily = data.get("daily", {})
            temps = [t for t in (daily.get("temperature_2m_max") or []) if t is not None]
            precips = [p for p in (daily.get("precipitation_sum") or []) if p is not None]
            if not temps or len(temps) < 2:
                continue

            # Temperature anomaly
            mean_temp = statistics.mean(temps[:-1]) if len(temps) > 1 else temps[0]
            latest_temp = temps[-1]
            temp_dev = latest_temp - mean_temp

            if temp_dev > 5:
                severity = 80
                label = "EXTREME"
            elif temp_dev > 3:
                severity = 55
                label = "MODERATE"
            else:
                severity = 0
                label = None

            if label:
                india_score = 25 if "India" in zone["name"] or "South Asia" in zone["name"] else 5
                signals.append(
                    self.std_signal(
                        id=f"climate-temp-{zone['name'].replace(' ','_')}-{datetime.now(UTC).strftime('%Y%m%d')}",
                        title=f"Temperature Anomaly: {zone['name']} ({label})",
                        summary=f"{latest_temp:.1f}°C vs 30-day mean {mean_temp:.1f}°C (deviation +{temp_dev:.1f}°C)",
                        domain="climate",
                        severity=severity,
                        india_score=india_score,
                        raw={"zone": zone["name"], "type": "temperature", "deviation": round(temp_dev, 2)},
                        tags=["climate", "anomaly", "temperature"],
                        latitude=zone["lat"],
                        longitude=zone["lon"],
                    )
                )

            # Precipitation anomaly
            if precips and len(precips) > 1:
                mean_precip = statistics.mean(precips[:-1])
                latest_precip = precips[-1]
                precip_dev = latest_precip - mean_precip

                if precip_dev > 80:
                    p_sev = 80
                    p_label = "EXTREME"
                elif precip_dev > 40:
                    p_sev = 55
                    p_label = "MODERATE"
                else:
                    p_sev = 0
                    p_label = None

                if p_label:
                    india_score = 25 if "India" in zone["name"] or "South Asia" in zone["name"] else 5
                    signals.append(
                        self.std_signal(
                            id=f"climate-precip-{zone['name'].replace(' ','_')}-{datetime.now(UTC).strftime('%Y%m%d')}",
                            title=f"Precipitation Anomaly: {zone['name']} ({p_label})",
                            summary=f"{latest_precip:.1f}mm vs 30-day mean {mean_precip:.1f}mm (deviation +{precip_dev:.1f}mm)",
                            domain="climate",
                            severity=p_sev,
                            india_score=india_score,
                            raw={"zone": zone["name"], "type": "precipitation", "deviation": round(precip_dev, 2)},
                            tags=["climate", "anomaly", "precipitation"],
                            latitude=zone["lat"],
                            longitude=zone["lon"],
                        )
                    )
        return signals
