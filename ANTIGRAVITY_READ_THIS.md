# ANTIGRAVITY — READ THIS FILE FIRST BEFORE WRITING ANY CODE

## Your Task

Read the file `GOE_Feed_Integration_Prompt.md` located in this same folder. That file contains the complete, authoritative specification for what you must build. Every detail about which connectors to create, what poll intervals to use, which Redis keys to write, and how to register everything in the scheduler is in that file.

This file (`ANTIGRAVITY_READ_THIS.md`) is your **entry point and execution checklist only**. All technical specs are in `GOE_Feed_Integration_Prompt.md`.

---

## Step 0 — Understand the Codebase Before Writing Anything

Before touching a single file, read and internalize the following files in this project:

```
apps/api/ingestion/base_connector.py        ← The interface every connector must follow
apps/api/ingestion/scheduler.py             ← Where you register connectors
apps/api/config.py                          ← Where all API keys / settings live
apps/api/ingestion/connectors/rss_aggregator.py   ← Example of existing connector
apps/api/ingestion/connectors/usgs.py             ← Example of existing connector
apps/api/ingestion/connectors/nasa_firms.py       ← Example of existing connector
apps/api/models/intelligence.py             ← IntelligenceItem model (signal output)
apps/api/models/signal.py                   ← RawSignal model
.env.example                                ← Env var pattern
docker-compose.yml                          ← Services available (Redis, Postgres, Neo4j)
```

Do not deviate from the `BaseConnector` interface. Every connector you write must extend it.

---

## Step 1 — Read the Full Specification

Open and fully read: **`GOE_Feed_Integration_Prompt.md`**

That file is divided into 22 sections. Each section corresponds to one or more connector files you must create or upgrade. The sections are:

| Section | What to build |
|---------|--------------|
| 1 | `mass_rss.py` — 435+ RSS/Atom feeds, server-side aggregation, 15-min poll |
| 2 | `gov_advisories.py` — US State Dept, UK FCDO, AU DFAT, NZ MFAT, 13 US Embassy feeds, 4 health feeds |
| 3 | `cyber_ioc.py` — 6 threat intel feeds (Feodo, URLhaus, C2Intel, OTX, AbuseIPDB, Ransomware.live) |
| 4 | `natural_disasters.py` — USGS M4.5+ + GDACS + NASA EONET, Haversine dedup |
| 5 | `nasa_firms.py` — upgrade existing, add MODIS_NRT, confidence filter |
| 6 | `climate_anomalies.py` — Open-Meteo ERA5, 15 monitored zones, 1-hour poll |
| 7 | `aviation_delays.py` — FAA ASWS + AviationStack + ICAO NOTAM |
| 8 | `internet_outages.py` — Cloudflare Radar API |
| 9 | `gps_jamming.py` — gpsjam.org H3 hex grid, 12 conflict region tags |
| 10a | `yahoo_finance.py` — upgrade, expand symbols, staggered batching |
| 10b | `coingecko.py` — upgrade, add Fear & Greed, BTC hash rate |
| 10c | `fred_economic.py` — FRED API, 8 macro series |
| 10d | `eia_energy.py` — EIA API, WTI + natural gas |
| 10e | `polymarket.py` — Polymarket Gamma API, JA3 retry strategy |
| 10f | `bis_data.py` — BIS central bank rates + REER, daily poll |
| 10g | `wto_trade.py` — WTO RSS feeds |
| 11 | `humanitarian.py` — HAPI + UNHCR + ReliefWeb + WorldPop |
| 12 | `oref_alerts.py` — Israel OREF rocket alerts, WAF bypass, wave detection |
| 13 | `iran_liveuamap.py` — LiveUAMap fallback chain (RSS → scrape → GDELT proxy) |
| 14 | `gdelt.py` — upgrade, add 7 themed query streams |
| 15 | `health_feeds.py` — 15 WHO/CDC/ECDC/ProMED/IFRC feeds |
| 16 | `live_streams.py` — HLS + YouTube stream catalog, health-check validation |
| 17 | `scheduler.py` — register ALL new connectors |
| 18 | `config.py` — add ALL new Optional[str] settings |
| 19 | `.env.example` — add all new keys with registration links |

---

## Step 2 — Implement in This Order

Work through the sections in this order to avoid import errors:

1. **`config.py`** — add all new settings first (Section 18). Nothing else compiles without this.
2. **`.env.example`** — add all new keys (Section 19).
3. **Each connector file** (Sections 1–16) — create or upgrade one file at a time. After each file, verify it compiles (`python -c "from apps.api.ingestion.connectors.FILENAME import CLASS"`).
4. **`scheduler.py`** — add all new imports and register all connectors in `connector_list` (Section 17). Do this last.

---

## Step 3 — Rules You Must Follow

### 1. Always extend `BaseConnector`
```python
from ..base_connector import BaseConnector

class MyNewConnector(BaseConnector):
    SOURCE_NAME = "my_source"           # snake_case, unique, used as Redis key suffix
    POLL_INTERVAL_SECONDS = 900         # Must match spec in GOE_Feed_Integration_Prompt.md
    CACHE_TTL_SECONDS = 900             # Must match spec

    async def fetch(self):
        return await self.fetch_json("https://example.com/api")

    async def parse(self, payload) -> list[dict]:
        return [self.std_signal(...) for item in payload]
```

### 2. Always use `std_signal()` to build signal dicts
```python
return self.std_signal(
    id="unique-stable-id",          # Must be stable across re-fetches (use item's own ID, not random)
    title="Human-readable title",
    summary="Brief description",
    domain="geopolitics",           # See DOMAIN_MAP in spec
    severity=50,                    # 0–100
    india_score=20,                 # 0–100 relevance to India
    url="https://source.url",
    published_at="2026-01-01T00:00:00Z",
    raw={"key": "original data"},
    tags=["tag1", "tag2"],
)
```

### 3. Never swallow exceptions in `fetch()` or `parse()`
`BaseConnector.run()` already catches all exceptions, calls `_mark_error()`, and returns `[]`. Do not add try/except inside your connector methods — let exceptions bubble up naturally.

### 4. Use `self.fetch_json()` and `self.fetch_text()` — never call `httpx` directly
These methods are provided by `BaseConnector` and use the shared `httpx.AsyncClient` with proper headers, timeouts, and redirects already configured.

### 5. Redis key naming — follow the project convention exactly
```
goe:last_fetch:{SOURCE_NAME}       ← managed by BaseConnector.run(), do not touch
goe:cache:{SOURCE_NAME}            ← managed by BaseConnector.run(), do not touch
goe:source_health:{SOURCE_NAME}    ← managed by BaseConnector, do not touch
goe:geo:{ip}                       ← you manage this for IOC geo-enrichment (TTL 86400s)
goe:disaster_dedup:{date}          ← you manage this for disaster Haversine dedup (TTL 86400s)
goe:live_streams                   ← you manage this for stream catalog (TTL 3600s)
goe:digest:{variant}               ← you manage this for RSS digest (TTL 900s)
goe:feed:{url_hash}                ← you manage this for per-feed RSS cache (TTL 600s)
goe:advisory:{country_code}        ← you manage this for advisory cache (TTL 1800s)
```

### 6. All new API keys must be `Optional[str] = None` in config.py
```python
# In apps/api/config.py — add to the Settings class:
FRED_API_KEY: Optional[str] = None
EIA_API_KEY: Optional[str] = None
# etc.
```
Each connector must gracefully return `[]` when its key is `None` — never raise an error when a key is missing.

### 7. For the mass RSS connector — use `asyncio.gather()` with per-feed timeouts
```python
import asyncio
import hashlib

async def _fetch_one_feed(self, name: str, url: str):
    try:
        async with asyncio.timeout(8.0):   # 8s per-feed timeout (per spec)
            text = await self.fetch_text(url)
            return (name, url, text)
    except Exception:
        return (name, url, None)           # Return None on failure, don't raise

# Batch 20 feeds at a time (per spec: 20 concurrent fetches, 25s total deadline)
async with asyncio.timeout(25.0):
    results = await asyncio.gather(*[self._fetch_one_feed(n, u) for n, u in batch])
```

### 8. For the OREF connector — use the fallback chain in order
Try sources in this order, moving to next if current fails:
1. `https://www.oref.org.il/WarningMessages/alert/alerts.json` with browser-like headers
2. `https://api.tzevaadom.co.il/notifications`
3. `https://red-alert.space/api/v1/alerts`

### 9. Install new dependencies properly
Before using any new library, check if it exists:
```bash
pip show h3 feedparser geopy aiofiles 2>/dev/null
```
Add missing ones to `requirements.txt` (or wherever your project manages deps):
```
feedparser>=6.0.11
h3>=3.7.7
geopy>=2.4.1
aiofiles>=23.0.0
```

---

## Step 4 — Verification Checklist

After implementing everything, verify:

- [ ] `python -m py_compile apps/api/config.py` — no errors
- [ ] `python -m py_compile apps/api/ingestion/scheduler.py` — no errors
- [ ] Every new connector file compiles: `python -m py_compile apps/api/ingestion/connectors/*.py`
- [ ] `len(scheduler.connectors)` in the lifespan log shows the expected count (was 14, should now be ~30+)
- [ ] No connector has `SOURCE_NAME` collision with another (they must all be unique)
- [ ] All connectors that require API keys return `[]` gracefully when the key is `None` or empty
- [ ] The mass RSS connector is registered and the old `RSSAggregatorConnector` is either removed from the list or kept alongside (do not delete the file, just remove from `connector_list` if replacing)
- [ ] `.env.example` has a comment with the registration URL for every new key

---

## Step 5 — Do Not Do These Things

- **Do not** create a new scheduler or change the `IntervalTrigger` setup — all connectors use the same 60-second check interval; the `POLL_INTERVAL_SECONDS` on each connector controls actual fetch frequency via `_should_fetch()`
- **Do not** use `requests` (sync) — this is an async codebase; use `self.fetch_json()` / `self.fetch_text()` or `asyncio.to_thread()` for blocking calls
- **Do not** store secrets in code — all API keys go through `settings.YOUR_KEY` from `config.py`
- **Do not** change `BaseConnector` — it is the shared interface; extend it, do not modify it
- **Do not** change `GOEIntelligenceEngine` — signal processing is handled by the engine after your connector returns items
- **Do not** change `main.py` — the scheduler is already wired up; you only change `scheduler.py`
- **Do not** hardcode poll intervals anywhere except the connector's `POLL_INTERVAL_SECONDS` class attribute

---

## Reference: Poll Intervals from the Spec

| Interval | Connectors |
|----------|-----------|
| 5 min (300s) | USGS/disasters, aviation delays, internet outages, OREF alerts, Iran LiveUAMap, Yahoo Finance, CoinGecko, Polymarket |
| 10 min (600s) | GDELT, Cyber IOCs |
| 15 min (900s) | Mass RSS aggregator (all 435+ feeds) |
| 30 min (1800s) | ACLED, NASA FIRMS, Government advisories, Global health feeds |
| 1 hour (3600s) | Climate anomalies, FRED, EIA, WTO trade, Humanitarian, Live stream catalog, GPS jamming |
| 24 hours (86400s) | BIS central bank data |

---

## You Are Ready

You now have:
1. This file — execution rules and checklist
2. `GOE_Feed_Integration_Prompt.md` — the full technical specification

Start with Step 2 above (config.py first, scheduler.py last). Implement each connector exactly as specified. Do not skip sections.
