"""Section 12 – OREF Rocket Alerts (Israel Home Front Command, 5-min poll)."""
from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings

OREF_URLS = [
    "https://www.oref.org.il/WarningMessages/alert/alerts.json",
    "https://api.tzevaadom.co.il/notifications",
    "https://red-alert.space/api/v1/alerts",
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://www.oref.org.il/12481-he/Pakar.aspx",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="122"',
    "sec-fetch-site": "same-origin",
}

ALERT_TYPE_MAP = {
    "1": "rockets_missiles",
    "2": "hostile_aircraft",
    "3": "earthquake",
    "4": "radiological",
    "6": "tsunami",
    "7": "hostile_fire",
}

# Sliding window for wave detection
_recent_alerts: deque[datetime] = deque(maxlen=100)


class OREFAlertsConnector(BaseConnector):
    SOURCE_NAME = "oref_rocket_alerts"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 60

    async def fetch(self):
        # Try fallback chain
        for url in OREF_URLS:
            try:
                headers = BROWSER_HEADERS.copy() if "oref.org.il" in url else {}
                if settings.OREF_PROXY_URL and "oref.org.il" in url:
                    # proxy support would require custom transport – skip for now
                    pass
                text = await self.fetch_text(url, headers=headers)
                data = json.loads(text) if text.strip() else []
                if data:
                    return data
            except Exception:
                continue
        return []

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        alerts = payload if isinstance(payload, list) else [payload]
        signals = []
        now = datetime.now(UTC)

        for alert in alerts:
            alert_id = str(alert.get("id") or alert.get("notificationId") or "")
            cat = str(alert.get("cat") or alert.get("type") or "1")
            alert_type = ALERT_TYPE_MAP.get(cat, "unknown")
            locations = alert.get("data") or alert.get("cities") or alert.get("locations") or []
            if isinstance(locations, str):
                locations = [locations]
            desc = alert.get("desc") or alert.get("description") or ""
            title_text = alert.get("title") or ""

            display_locations = locations[:5]
            loc_str = ", ".join(str(l) for l in display_locations)

            signals.append(
                self.std_signal(
                    id=f"oref-{alert_id}-{now.date()}",
                    title=f"OREF Alert: {alert_type} — {loc_str}",
                    summary=f"Active alert in: {', '.join(str(l) for l in locations)}",
                    domain="defense",
                    severity=90,
                    india_score=5,
                    raw={
                        "alert_type": alert_type,
                        "locations": [str(l) for l in locations],
                        "cat": cat,
                        "description": desc,
                    },
                    tags=["oref", "rocket_alert", "israel", alert_type],
                    latitude=31.5,
                    longitude=34.9,
                )
            )
            _recent_alerts.append(now)

        # Wave detection: 3+ alerts in 10-min window
        cutoff = now.timestamp() - 600
        recent = [t for t in _recent_alerts if t.timestamp() > cutoff]
        if len(recent) >= 3:
            signals.append(
                self.std_signal(
                    id=f"oref-wave-{now.strftime('%Y%m%dT%H%M')}",
                    title=f"OREF Multi-Wave Barrage: {len(recent)} alerts in 10 min",
                    summary=f"Barrage detected: {len(recent)} alerts within sliding 10-minute window",
                    domain="defense",
                    severity=95,
                    india_score=5,
                    raw={"wave_count": len(recent)},
                    tags=["oref", "rocket_alert", "barrage", "israel"],
                    latitude=31.5,
                    longitude=34.9,
                )
            )
        return signals
