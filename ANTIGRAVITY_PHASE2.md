# ANTIGRAVITY — PHASE 2 INTEGRATION PROMPT
# GOE Platform: Activate Real API Keys + Add Missing Sources

---

## CURRENT STATE OF THE PROJECT (READ THIS FIRST)

The project already has connector files for most sources. Your job in this phase is:
1. **Wire in the real API keys** that are now available (update `.env` and `config.py`)
2. **Fix and upgrade connectors** that were built with placeholder logic
3. **Add three missing connectors** that were never created: `ucdp.py`, `nga_navwarnings.py`, `aisstream` (WebSocket relay)
4. **Do NOT** create new connector files for sources that already have working connectors
5. **Do NOT** touch `scheduler.py` — all connectors are already registered

**SKIP ENTIRELY** (not available / not needed):
- Wingbits — no API obtained, skip completely
- Travelpayouts — no API obtained, skip completely

---

## REAL API KEYS NOW AVAILABLE

Add/update ALL of these in `.env` and ensure the matching field exists in `config.py`:

```dotenv
# NASA EarthData — JWT token for FIRMS authentication
NASA_EARTHDATA_TOKEN=eyJ0eXAiOiJKV1QiLCJvcmlnaW4iOiJFYXJ0aGRhdGEgTG9naW4iLCJzaWciOiJlZGxqd3RwdWJrZXlfb3BzIiwiYWxnIjoiUlMyNTYifQ.eyJ0eXBlIjoiVXNlciIsInVpZCI6Im1hbmFic2VuMDA2IiwiZXhwIjoxNzc5Mjg0MDU5LCJpYXQiOjE3NzQxMDAwNTksImlzcyI6Imh0dHBzOi8vdXJzLmVhcnRoZGF0YS5uYXNhLmdvdiIsImlkZW50aXR5X3Byb3ZpZGVyIjoiZWRsX29wcyIsImFjciI6ImVkbCIsImFzc3VyYW5jZV9sZXZlbCI6M30.A48OoONmqJYFo-ZeDf0wnBDwNsG6WPs4sAHp84uFxK0WEgjVDHjcsSGWSGiiirdRhuTNjiPyMQ_4ntZOo42rUnV17YgBieeZGT7U3lXn2q2PC7ZZzmK2osl-bVqkdSBwba1IjARNEgHSx36fM1k59DQphOocTnlsPdXXgD3Fy80dAblElZ__wzcqqLRP5rqEwO4rz4d2jF8qMmRXXY3AnkS6bBIiSrNFTDsCUAA16QkFIKy8d9cxC5FZ-e8YjupZ5igdp2j1_lE6tZeULq2gMUFvz8vvvrKVXAdhkilfIc2P97iCTBgwiBTEW7dMAN4MjisCdo5JiYRh7QG17LDClA

# ipinfo.io — IP geolocation (50K/month free)
IPINFO_TOKEN=e2d1d86fee2b21

# AISStream — maritime vessel tracking WebSocket
AISSTREAM_API_KEY=3c72fca48f2fd574d479a8e4ff141a5accebea38

# OpenSky Network — OAuth2 client credentials (NOT username/password)
OPENSKY_CLIENT_ID=manabsen006@gmail.com-api-client
OPENSKY_CLIENT_SECRET=FBV8D9aH8aN2CYSwQODl7oiTIvLlRKJM

# CoinGecko Demo API key
COINGECKO_API_KEY=CG-xxXbo4Cx8srdWQE38Z9s9weQ

# HAPI humanitarian — already set to string, just fill it
HAPI_APP_IDENTIFIER=goe-intelligence-platform
```

**Note on NASA**: The `NASA_FIRMS_KEY` (MAP_KEY) is separate from the EarthData JWT token. The JWT token is for authenticating to EarthData — you still need the FIRMS MAP_KEY. To get it: after EarthData login, visit https://firms.modaps.eosdis.nasa.gov/api/ and click "Get MAP_KEY". Use the `NASA_EARTHDATA_TOKEN` as the Bearer token for that request. Store the resulting short MAP_KEY as `NASA_FIRMS_KEY` in `.env`.

---

## TASK 1 — Update `config.py`

Open `apps/api/config.py`. The `Settings` class is missing these fields. Add them to the class:

```python
# NASA
NASA_EARTHDATA_TOKEN: Optional[str] = None   # JWT for EarthData auth

# OpenSky — NEW OAuth2 format (replaces username/password)
OPENSKY_CLIENT_ID: Optional[str] = None
OPENSKY_CLIENT_SECRET: Optional[str] = None
# Keep the old fields for backward compat but they are now unused:
# OPENSKY_USERNAME and OPENSKY_PASSWORD already exist — leave them

# Geo-enrichment
IPINFO_TOKEN: Optional[str] = None

# AISStream WebSocket
AISSTREAM_API_KEY: Optional[str] = None

# UCDP (no key needed — field not required, but add flag)
UCDP_ENABLED: bool = True

# NGA Nav Warnings
NGA_NAVWARNINGS_ENABLED: bool = True
```

---

## TASK 2 — Fix `opensky.py`

The current connector uses username/password auth. OpenSky now uses **OAuth2 client credentials** (the new API format). Rewrite `apps/api/ingestion/connectors/opensky.py` completely:

```
SOURCE_NAME = "opensky_aviation"
POLL_INTERVAL_SECONDS = 900   # 15 min — free tier: 4000 credits/day; 1 call = ~1 credit; 96 calls/day max safely
CACHE_TTL_SECONDS = 900
```

**Authentication**: OpenSky OAuth2 token endpoint:
```
POST https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded
Body: grant_type=client_credentials&client_id={OPENSKY_CLIENT_ID}&client_secret={OPENSKY_CLIENT_SECRET}
```
Cache the bearer token in Redis key `goe:opensky_token` with TTL = 3500 seconds (tokens last 3600s). On fetch, check Redis first; only re-authenticate if expired.

**Flight data endpoint** (use authenticated bearer token):
```
GET https://opensky-network.org/api/states/all
Authorization: Bearer {token}
```

**Military callsign filter** — only emit signals for military/government aircraft. Filter `states` array where `state[1]` (callsign) starts with any of:
```python
MILITARY_PREFIXES = [
    "RCH", "REACH", "RRR", "GAF", "FORTE", "JAKE", "MAGMA",
    "SPAR", "VENUS", "BOXER", "ASCOT", "ATLAS", "COMET",
    "EAGLE", "HAWK", "CONDOR", "DUKE", "KING", "BARON",
]
```
Also include any callsign that matches the pattern of known military registration prefixes. If no authenticated key, fall back to anonymous (no auth header) and fetch only — the anonymous endpoint still works but with lower limits.

**Signal output per aircraft**:
```python
self.std_signal(
    id=f"opensky-{icao24}-{date}",   # icao24 = state[0], date = today's date for daily dedup
    title=f"Military flight: {callsign}",
    summary=f"{callsign} at alt {baro_alt}m, speed {velocity}m/s, heading {heading}°",
    domain="defense",
    severity=35,
    india_score=5,
    latitude=lat,    # state[6]
    longitude=lon,   # state[5]
    raw={"icao24": icao24, "callsign": callsign, "velocity": velocity, "baro_altitude": baro_alt, "on_ground": on_ground},
    tags=["aviation", "military", "opensky"],
)
```

---

## TASK 3 — Fix `nasa_firms.py`

The connector currently uses `NASA_FIRMS_KEY` but has no EarthData JWT auth. Update it to use the JWT token for the FIRMS API requests that require authentication.

The FIRMS CSV endpoint accepts the MAP_KEY in the URL. The JWT token is used differently — for the EarthData login. The MAP_KEY is still the primary credential for the CSV download.

Update `nasa_firms.py`:
1. Keep using `settings.NASA_FIRMS_KEY` in the URL as-is
2. Add the `NASA_EARTHDATA_TOKEN` as a fallback auth header for requests that return 401:
```python
headers = {}
if settings.NASA_EARTHDATA_TOKEN:
    headers["Authorization"] = f"Bearer {settings.NASA_EARTHDATA_TOKEN}"
```
3. Raise confidence threshold: only include rows where `confidence` column >= 50 (already done if implemented correctly — verify the parse method filters on confidence)
4. Add FRP-based severity: `severity = min(100, int(float(frp_value) / 10))` where `frp` is the Fire Radiative Power column (column index 13 in VIIRS CSV)

Full VIIRS CSV columns in order:
```
latitude, longitude, bright_ti4, scan, track, acq_date, acq_time,
satellite, instrument, confidence, version, bright_ti5, frp, daynight
```

---

## TASK 4 — Fix `cyber_ioc.py` (add real ipinfo.io token)

The connector already has geo-enrichment logic calling ipinfo.io. It just needs to pass the real token. Find the `_geo_lookup` method and update the ipinfo.io URL:

```python
# Change this:
url = f"https://ipinfo.io/{ip}/json"

# To this (with token):
token = settings.IPINFO_TOKEN
if token:
    url = f"https://ipinfo.io/{ip}/json?token={token}"
else:
    url = f"https://ipinfo.io/{ip}/json"
```

Also add the `IPINFO_TOKEN` setting import — it should come from `settings.IPINFO_TOKEN` which you added in Task 1.

**Rate management**: ipinfo.io free = 50,000/month. You process up to 250 IPs per run, every 10 minutes = 250 × 144 = 36,000/day theoretical max. The Redis geo cache (TTL=86400) prevents re-querying the same IP for 24 hours. This is fine as long as IOC IPs rotate. No changes needed to the caching logic.

---

## TASK 5 — Fix `coingecko.py` (add real API key)

The connector fetches from `api.coingecko.com` but doesn't pass the Demo API key. Update every CoinGecko URL in the connector to include the key:

For **Demo key** usage, add this header to all CoinGecko requests:
```python
headers = {}
if settings.COINGECKO_API_KEY:
    headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
```

Use `self.fetch_json(url, headers=headers)` for all three CoinGecko endpoints (markets, trending, global).

Also add the Fear & Greed index fetch (no key needed — different domain):
```python
results["fear_greed"] = await self.fetch_json(
    "https://api.alternative.me/fng/?limit=30"
)
```

And BTC hash rate (no key needed):
```python
results["btc_hashrate"] = await self.fetch_json(
    "https://mempool.space/api/v1/mining/hashrate/pools/1m"
)
```

Parse these in `parse()` and emit as signals with `domain="economics"`, `tags=["crypto", "coingecko"]`.

---

## TASK 6 — Fix `humanitarian.py` (HAPI app identifier)

The HAPI requests need `HAPI_APP_IDENTIFIER` in the header. The connector already has this logic. Just verify the header is being set as `X-HDX-HAPI-APP-IDENTIFIER`. Confirm it reads from `settings.HAPI_APP_IDENTIFIER` and that `.env` has `HAPI_APP_IDENTIFIER=goe-intelligence-platform`.

Also add UNHCR endpoint to the same connector (currently missing from `parse()`):
```python
# In fetch():
try:
    results["unhcr"] = await self.fetch_json(
        "https://api.unhcr.org/population/v1/population/?limit=20&sortBy=total&sortOrder=desc"
    )
except Exception:
    results["unhcr"] = None

# In parse() — add UNHCR handling:
if payload.get("unhcr"):
    entries = payload["unhcr"].get("items", []) or []
    for entry in entries[:10]:
        total = entry.get("total", 0) or 0
        country = entry.get("coo_name") or entry.get("coa_name") or "Unknown"
        severity = 80 if total > 1_000_000 else 60 if total > 500_000 else 40
        signals.append(self.std_signal(
            id=f"unhcr-{entry.get('year')}-{entry.get('coo')}-{entry.get('coa')}",
            title=f"UNHCR: {int(total):,} displaced from {country}",
            summary=f"Population of concern: {int(total):,} people",
            domain="health",
            severity=severity,
            india_score=15 if "India" in country or "Pakistan" in country or "Bangladesh" in country or "Myanmar" in country else 5,
            url="https://api.unhcr.org/population/v1/population/",
            raw=entry,
            tags=["unhcr", "displacement", "humanitarian"],
        ))
```

---

## TASK 7 — CREATE `ucdp.py` (new connector)

**File to create**: `apps/api/ingestion/connectors/ucdp.py`

UCDP (Uppsala Conflict Data Program) is completely free, no registration, no key.

```python
"""UCDP – Uppsala Conflict Data Program (free, no key, 1-hour poll)."""
from __future__ import annotations
from datetime import UTC, datetime
from ..base_connector import BaseConnector

class UCDPConnector(BaseConnector):
    SOURCE_NAME = "ucdp_conflicts"
    POLL_INTERVAL_SECONDS = 3600   # 1 hour — data updates daily, not real-time
    CACHE_TTL_SECONDS = 3600

    GED_URL = "https://ucdpapi.pcr.uu.se/api/gedevents/23.1?pagesize=100&page=1"

    async def fetch(self):
        try:
            return await self.fetch_json(self.GEST_URL)
        except Exception:
            return {}

    async def parse(self, payload) -> list[dict]:
        results = payload.get("Result", []) or []
        signals = []
        for event in results[:50]:
            deaths = int(event.get("best", 0) or 0)
            signals.append(self.std_signal(
                id=f"ucdp-{event.get('id')}",
                title=f"UCDP: {event.get('conflict_name', 'Armed conflict event')}",
                summary=(
                    f"{event.get('type_of_violence_label', 'Violence')} in "
                    f"{event.get('country', 'Unknown')}. "
                    f"Deaths: {deaths}. "
                    f"Actors: {event.get('side_a', '')} vs {event.get('side_b', '')}."
                ),
                domain="defense",
                severity=90 if deaths > 100 else 75 if deaths > 10 else 55 if deaths > 0 else 40,
                india_score=30 if any(k in str(event) for k in ["India", "Pakistan", "Kashmir", "Bangladesh", "Myanmar"]) else 5,
                url=f"https://ucdp.uu.se/event/{event.get('id')}",
                published_at=event.get("date_start") or datetime.now(UTC).isoformat(),
                raw=event,
                latitude=_safe_float(event.get("latitude")),
                longitude=_safe_float(event.get("longitude")),
                tags=["ucdp", "conflict", event.get("type_of_violence_label", "").lower().replace(" ", "_")],
            ))
        return signals

def _safe_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
```

**Note**: Fix the typo `self.GEST_URL` → `self.GEST_URL` should be `self.GED_URL`.

After creating this file, **add it to `scheduler.py`**:
```python
# Add import at top of scheduler.py with the other new connectors:
from .connectors.ucdp import UCDPConnector

# Add to connector_list in GOEScheduler.__init__():
UCDPConnector(*args),
```

---

## TASK 8 — CREATE `nga_navwarnings.py` (new connector)

**File to create**: `apps/api/ingestion/connectors/nga_navwarnings.py`

NGA (National Geospatial-Intelligence Agency) navigational warnings — completely free, no key. RSS/JSON feed of maritime navigation hazards, military exercise zones, cable repair areas.

```python
"""NGA – Navigational Warnings (free, no key, 1-hour poll)."""
from __future__ import annotations
import re
from datetime import UTC, datetime
import feedparser
from ..base_connector import BaseConnector

# Keywords that make a NAVWARN strategically significant
HIGH_SIGNIFICANCE_KEYWORDS = [
    "missile", "exercise", "weapons", "firing", "military",
    "cable", "pipeline", "prohibited", "exclusion zone",
    "live fire", "torpedo", "naval", "submarine",
]

class NGANavWarningsConnector(BaseConnector):
    SOURCE_NAME = "nga_navwarnings"
    POLL_INTERVAL_SECONDS = 3600   # 1 hour
    CACHE_TTL_SECONDS = 3600

    FEEDS = [
        "https://msi.nga.mil/api/publications/broadcast-warn?output=rss",
        "https://msi.nga.mil/api/publications/query?output=json&status=active&msgYear=2026&navArea=IV&includePoints=true",
    ]

    async def fetch(self):
        results = {}
        # RSS broadcast warnings
        try:
            results["rss"] = await self.fetch_text(self.FEEDS[0])
        except Exception:
            results["rss"] = None
        # JSON query for active warnings (NavArea IV = N Atlantic; covers multiple areas)
        for nav_area in ["IV", "XI", "XVI"]:   # Atlantic, Pacific, Indian Ocean
            try:
                url = (
                    f"https://msi.nga.mil/api/publications/query"
                    f"?output=json&status=active&navArea={nav_area}&includePoints=true"
                )
                results[f"json_{nav_area}"] = await self.fetch_json(url)
            except Exception:
                results[f"json_{nav_area}"] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals = []

        # Parse RSS feed
        if payload.get("rss"):
            feed = feedparser.parse(payload["rss"])
            for entry in feed.entries[:30]:
                title = (entry.get("title") or "NGA Nav Warning").strip()
                text = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")
                text_lower = (title + " " + text).lower()
                is_significant = any(kw in text_lower for kw in HIGH_SIGNIFICANCE_KEYWORDS)
                if not is_significant:
                    continue   # Skip routine navigation warnings
                signals.append(self.std_signal(
                    id=f"nga-{entry.get('id', title[:40])}",
                    title=f"NGA NavWarn: {title[:80]}",
                    summary=text[:400],
                    domain="defense",
                    severity=55,
                    india_score=10 if any(k in text_lower for k in ["india", "arabian", "bay of bengal", "indian ocean"]) else 5,
                    url=entry.get("link", "https://msi.nga.mil/"),
                    published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                    raw={"source": "nga_rss"},
                    tags=["nga", "navwarning", "maritime"],
                ))

        # Parse JSON responses
        for key in ["json_IV", "json_XI", "json_XVI"]:
            data = payload.get(key)
            if not data:
                continue
            publications = data if isinstance(data, list) else data.get("publications", []) or []
            for pub in publications[:20]:
                text = (pub.get("text") or pub.get("msgText") or "").lower()
                is_significant = any(kw in text for kw in HIGH_SIGNIFICANCE_KEYWORDS)
                if not is_significant:
                    continue
                signals.append(self.std_signal(
                    id=f"nga-json-{pub.get('msgNumber', pub.get('id', 'unknown'))}",
                    title=f"NGA NavWarn: {pub.get('subregion', key)} — {pub.get('msgNumber', '')}",
                    summary=(pub.get("text") or pub.get("msgText") or "")[:400],
                    domain="defense",
                    severity=55,
                    india_score=5,
                    url="https://msi.nga.mil/NavWarnings",
                    raw=pub,
                    tags=["nga", "navwarning", "maritime", key.split("_")[1]],
                ))

        return signals
```

After creating this file, **add it to `scheduler.py`**:
```python
# Add import:
from .connectors.nga_navwarnings import NGANavWarningsConnector

# Add to connector_list:
NGANavWarningsConnector(*args),
```

---

## TASK 9 — ADD AISStream TO WebSocket RELAY (`apps/ws/server.js`)

AISStream is a WebSocket-based maritime vessel tracking service. It cannot be integrated as a Python `BaseConnector` because it requires a persistent WebSocket connection. Integrate it into the existing Node.js WebSocket relay at `apps/ws/server.js`.

**Add the following to `apps/ws/server.js`** — insert this block AFTER the existing Redis subscriber setup (after line `console.log(\`GOE WebSocket server subscribed to ${count} Redis channels\`)`):

```javascript
// ── AISStream Maritime Vessel Tracking ────────────────────────────────────
const AISSTREAM_KEY = process.env.AISSTREAM_API_KEY || "";
let aisWs = null;
let aisReconnectTimer = null;

const STRATEGIC_BOUNDING_BOXES = [
  // Red Sea / Suez / Gulf of Aden
  [[10.0, 30.0], [30.0, 50.0]],
  // Persian Gulf / Strait of Hormuz
  [[22.0, 48.0], [30.0, 60.0]],
  // Strait of Malacca / South China Sea
  [[0.0, 95.0], [22.0, 120.0]],
  // Eastern Mediterranean / Levant
  [[30.0, 25.0], [42.0, 42.0]],
  // Indian Ocean shipping lanes
  [[-10.0, 50.0], [20.0, 80.0]],
];

function connectAISStream() {
  if (!AISSTREAM_KEY) {
    console.log("AISStream: no API key configured, skipping.");
    return;
  }

  aisWs = new WebSocket("wss://stream.aisstream.io/v0/stream");

  aisWs.on("open", () => {
    console.log("AISStream: connected");
    aisWs.send(JSON.stringify({
      APIKey: AISSTREAM_KEY,
      BoundingBoxes: STRATEGIC_BOUNDING_BOXES,
      FilterMessageTypes: ["PositionReport", "ShipStaticData"],
    }));
  });

  aisWs.on("message", async (data) => {
    try {
      const msg = JSON.parse(data.toString());
      const msgType = msg.MessageType;
      const meta = msg.MetaData || {};

      // Build a normalized vessel signal
      const vessel = {
        mmsi:       meta.MMSI || "",
        ship_name:  meta.ShipName || "",
        lat:        meta.latitude || 0,
        lon:        meta.longitude || 0,
        speed:      meta.ShipSpeed || 0,
        heading:    meta.TrueHeading || 0,
        msg_type:   msgType,
        time_utc:   meta.time_utc || new Date().toISOString(),
      };

      // Add static data if present
      if (msgType === "ShipStaticData") {
        const sd = msg.Message?.ShipStaticData || {};
        vessel.ship_type    = sd.Type || 0;
        vessel.destination  = sd.Destination || "";
        vessel.callsign     = sd.CallSign || "";
        vessel.length       = sd.Dimension?.A + sd.Dimension?.B || 0;

        // Flag naval vessels (ship_type 35 = military, 36 = sailing, etc.)
        vessel.is_naval = vessel.ship_type === 35;
      }

      // Publish raw vessel position to Redis for Python connectors to consume
      await redis.setex(
        `goe:ais_vessel:${vessel.mmsi}`,
        300,  // 5 min TTL — vessel positions stale after this
        JSON.stringify(vessel)
      );

      // Publish to AIS channel for WebSocket fan-out to frontend clients
      await redis.publish(
        "goe:ais_vessels",
        JSON.stringify({ type: "AIS_POSITION", data: vessel })
      );

    } catch (err) {
      // Silently ignore malformed AIS messages
    }
  });

  aisWs.on("close", (code, reason) => {
    console.log(`AISStream: disconnected (${code}). Reconnecting in 30s...`);
    aisWs = null;
    if (aisReconnectTimer) clearTimeout(aisReconnectTimer);
    aisReconnectTimer = setTimeout(connectAISStream, 30000);
  });

  aisWs.on("error", (err) => {
    console.error("AISStream error:", err.message);
    // close handler will trigger reconnect
  });
}

// Start AISStream connection
connectAISStream();
```

Also add `"goe:ais_vessels"` to the `CHANNELS` array at the top of `server.js` so vessel positions are forwarded to frontend WebSocket clients:
```javascript
// Change:
const CHANNELS = [
  "goe:live_signals",
  "goe:alerts",
  "goe:market_update",
  "goe:daily_brief_ready",
];
// To:
const CHANNELS = [
  "goe:live_signals",
  "goe:alerts",
  "goe:market_update",
  "goe:daily_brief_ready",
  "goe:ais_vessels",   // ← add this
];
```

Also add `AISSTREAM_API_KEY` to `docker-compose.yml` under the `ws` service environment:
```yaml
# In the ws service environment block, add:
AISSTREAM_API_KEY: "${AISSTREAM_API_KEY:-}"
```

---

## TASK 10 — Verify and fix `acled.py` rate limit

The ACLED free tier is ~10,000 rows/month. The current connector polls every 1800 seconds (30 min) fetching 50 rows = 50 × 48 × 31 = 74,400 rows/month. This exceeds the free limit.

**Fix in `apps/api/ingestion/connectors/acled.py`**:
```python
# Change poll interval:
POLL_INTERVAL_SECONDS = 21600  # once every 6 hours (4 times/day)
# 50 rows × 4 × 31 = 6,200 rows/month — safely within 10K limit

# Add date filter to only fetch last 24 hours of events:
from datetime import timedelta

# In fetch(), update params:
params = {
    "key": settings.ACLED_API_KEY,
    "email": settings.ACLED_EMAIL,
    "event_date": datetime.now(UTC).strftime("%Y-%m-%d"),
    "event_date_where": "BETWEEN",
    "event_date2": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d"),
    "limit": 50,
}
```

---

## TASK 11 — Verify and fix `aviation_delays.py` rate limit

AviationStack free tier = 100 API calls/month total. The connector must not exceed this.

**Fix in `apps/api/ingestion/connectors/aviation_delays.py`**:
1. Check the current AviationStack fetch logic — ensure it only queries a maximum of **5 airports per day** (rotate based on a daily selection)
2. Add a daily call counter in Redis: key `goe:aviationstack_calls:{date}`, max value = 3 per day (keeping 100/month = ~3.3/day)
3. If counter >= 3, skip AviationStack entirely for that day and rely on FAA ASWS + ICAO NOTAM only

```python
# Add to the AviationStack fetch section inside aviation_delays.py:
today = datetime.now(UTC).strftime("%Y-%m-%d")
calls_key = f"goe:aviationstack_calls:{today}"
calls_today = int(await self.redis.get(calls_key) or 0)
if calls_today >= 3:
    results["aviationstack"] = []   # Skip — daily limit reached
else:
    # ... existing AviationStack fetch logic ...
    await self.redis.incr(calls_key)
    await self.redis.expire(calls_key, 86400)
```

---

## TASK 12 — Update `.env.example`

Update `.env.example` to document all new keys with comments:

```dotenv
# ── NASA ──────────────────────────────────────────────────────────────────
# EarthData JWT token — from https://urs.earthdata.nasa.gov
NASA_EARTHDATA_TOKEN=your_earthdata_jwt_here
# FIRMS MAP_KEY — from https://firms.modaps.eosdis.nasa.gov/api/ (get after EarthData login)
NASA_FIRMS_KEY=your_firms_map_key_here

# ── OpenSky OAuth2 (replaces username/password) ───────────────────────────
# From https://opensky-network.org — create API client in account settings
OPENSKY_CLIENT_ID=your_email-api-client
OPENSKY_CLIENT_SECRET=your_client_secret_here

# ── IP Geolocation ────────────────────────────────────────────────────────
# From https://ipinfo.io/signup (free: 50K/month)
IPINFO_TOKEN=your_ipinfo_token_here

# ── Maritime Tracking ─────────────────────────────────────────────────────
# From https://aisstream.io (free: 1 WebSocket connection)
AISSTREAM_API_KEY=your_aisstream_key_here

# ── Crypto / Finance ──────────────────────────────────────────────────────
# CoinGecko Demo key — from https://www.coingecko.com/en/api/pricing
COINGECKO_API_KEY=CG-your_demo_key_here

# ── Humanitarian ──────────────────────────────────────────────────────────
# Any string — no account needed for HAPI
HAPI_APP_IDENTIFIER=goe-intelligence-platform
```

---

## TASK 13 — Add `package.json` dependency for `ws` in the relay

The `apps/ws/server.js` AISStream integration uses the `ws` WebSocket client. Verify `ws` is in `apps/ws/package.json`. If not present, add it:

```json
{
  "dependencies": {
    "ws": "^8.17.0",
    "ioredis": "^5.3.2"
  }
}
```

The `ws` package is used both as a **server** (existing code) and as a **client** (new AISStream connection). The same package handles both. No additional install needed if `ws` is already there.

---

## TASK 14 — Final verification checklist

After all changes, verify:

- [ ] `python -m py_compile apps/api/config.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/ucdp.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/nga_navwarnings.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/opensky.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/acled.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/aviation_delays.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/cyber_ioc.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/coingecko.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/humanitarian.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/connectors/nasa_firms.py` — no errors
- [ ] All new keys present in `.env`: `NASA_EARTHDATA_TOKEN`, `IPINFO_TOKEN`, `AISSTREAM_API_KEY`, `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, `COINGECKO_API_KEY`, `HAPI_APP_IDENTIFIER`
- [ ] All new keys declared in `config.py` Settings class
- [ ] `scheduler.py` imports and registers `UCDPConnector` and `NGANavWarningsConnector`
- [ ] `apps/ws/server.js` has the AISStream WebSocket block and `goe:ais_vessels` in CHANNELS
- [ ] `docker-compose.yml` passes `AISSTREAM_API_KEY` to the `ws` service

---

## SUMMARY — What you are doing in this phase

| Task | File | Action |
|------|------|--------|
| 1 | `config.py` | Add 5 new settings fields |
| 2 | `opensky.py` | Full rewrite — OAuth2 auth + military callsign filter |
| 3 | `nasa_firms.py` | Add EarthData JWT header + confidence filter + FRP severity |
| 4 | `cyber_ioc.py` | Add real ipinfo.io token to geo-enrichment |
| 5 | `coingecko.py` | Add Demo API key header + Fear&Greed + BTC hashrate |
| 6 | `humanitarian.py` | Verify HAPI header + add UNHCR parse block |
| 7 | `ucdp.py` | CREATE new connector (UCDP conflict data) |
| 8 | `nga_navwarnings.py` | CREATE new connector (maritime nav warnings) |
| 9 | `server.js` | ADD AISStream WebSocket relay block |
| 10 | `acled.py` | Reduce poll interval + add date filter (rate limit fix) |
| 11 | `aviation_delays.py` | Add Redis daily call counter (rate limit fix) |
| 12 | `.env` + `.env.example` | Add all real API keys |
| 13 | `package.json` | Verify `ws` dependency exists |
| 14 | `scheduler.py` | Register UCDPConnector + NGANavWarningsConnector |

**Do not touch**: `scheduler.py` (except adding 2 new connectors), `main.py`, `base_connector.py`, `database.py`, any router files, any model files, any core intelligence files.

**Sources fully covered after this phase** (matching worldmonitor.app):
ACLED ✓, GDELT ✓, UCDP ✓, LiveUAMap/Iran ✓, OpenSky ✓, AISStream ✓, AviationStack ✓, FAA ASWS ✓, ICAO NOTAM ✓, gpsjam.org ✓, NGA Nav Warnings ✓, USGS ✓, GDACS ✓, NASA EONET ✓, NASA FIRMS ✓, Open-Meteo ERA5 ✓, FRED ✓, EIA ✓, Yahoo Finance ✓, CoinGecko ✓, BIS ✓, WTO ✓, Polymarket ✓, C2IntelFeeds ✓, Ransomware.live ✓, ipinfo.io ✓, freeipapi.com ✓, HAPI ✓, UNHCR ✓, CDC ✓, ECDC ✓, WHO ✓, US State Dept ✓, Australia DFAT ✓, UK FCDO ✓, NZ MFAT ✓.

**Skipped** (no API obtained): Wingbits, Travelpayouts.
**WorldPop**: Available at worldpop.org — called on-demand from `humanitarian.py` for high-severity events only (severity >= 70), not a scheduled connector.
