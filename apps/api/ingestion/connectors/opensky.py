"""Section 7 – Aviation (OpenSky)."""
from __future__ import annotations

from datetime import UTC, datetime

from ...config import settings
from ..base_connector import BaseConnector

MILITARY_PREFIXES = [
    "RCH", "REACH", "RRR", "GAF", "FORTE", "JAKE", "MAGMA",
    "SPAR", "VENUS", "BOXER", "ASCOT", "ATLAS", "COMET",
    "EAGLE", "HAWK", "CONDOR", "DUKE", "KING", "BARON",
]


class OpenSkyConnector(BaseConnector):
    SOURCE_NAME = "opensky_aviation"
    POLL_INTERVAL_SECONDS = 900   # 15 min — free tier: 4000 credits/day; 1 call = ~1 credit; 96 calls/day max safely
    CACHE_TTL_SECONDS = 900

    URL = "https://opensky-network.org/api/states/all"
    AUTH_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

    async def fetch(self):
        token = None
        if settings.OPENSKY_CLIENT_ID and settings.OPENSKY_CLIENT_SECRET:
            token = await self.redis.get("goe:opensky_token")
            if not token:
                try:
                    resp = await self.http.post(
                        self.AUTH_URL,
                        data={
                            "grant_type": "client_credentials",
                            "client_id": settings.OPENSKY_CLIENT_ID,
                            "client_secret": settings.OPENSKY_CLIENT_SECRET,
                        },
                    )
                    resp.raise_for_status()
                    token_data = resp.json()
                    token = token_data.get("access_token")
                    if token:
                        await self.redis.setex("goe:opensky_token", 3500, token)
                except Exception:
                    pass

        headers = {}
        if token:
            # Type ignore or string cast in case token is returned as bytes from redis
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            headers["Authorization"] = f"Bearer {token}"

        try:
            return await self.fetch_json(self.URL, headers=headers)
        except Exception:
            return {}

    async def parse(self, payload) -> list[dict]:
        states = payload.get("states", []) or []
        signals = []
        today_date = datetime.now(UTC).strftime("%Y%m%d")

        for state in states:
            icao24 = state[0]
            callsign = (state[1] or "").strip() if len(state) > 1 else ""
            
            # Filter for military callsigns
            is_military = any(callsign.startswith(prefix) for prefix in MILITARY_PREFIXES)
            if not is_military:
                continue

            lon = state[5] if len(state) > 5 else None
            lat = state[6] if len(state) > 6 else None
            baro_alt = state[7] if len(state) > 7 else None
            on_ground = state[8] if len(state) > 8 else None
            velocity = state[9] if len(state) > 9 else None
            heading = state[10] if len(state) > 10 else None

            signals.append(
                self.std_signal(
                    id=f"opensky-{icao24}-{today_date}",
                    title=f"Military flight: {callsign}",
                    summary=f"{callsign} at alt {baro_alt}m, speed {velocity}m/s, heading {heading}°",
                    domain="defense",
                    severity=35,
                    india_score=5,
                    latitude=lat,
                    longitude=lon,
                    raw={
                        "icao24": icao24,
                        "callsign": callsign,
                        "velocity": velocity,
                        "baro_altitude": baro_alt,
                        "on_ground": on_ground,
                    },
                    tags=["aviation", "military", "opensky"],
                )
            )

        return signals
