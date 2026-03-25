# GOE Platform — Full Feed Integration Prompt
## Complete RSS/HTTP Polling Integration (WorldMonitor-Parity)

---

## CONTEXT: YOUR PROJECT ARCHITECTURE

You are working on the **GOE (Geopolitical Operations Engine)** — a Python/FastAPI intelligence platform with the following stack:

- **Backend**: FastAPI (async), Python 3.13, APScheduler
- **Databases**: PostgreSQL (via SQLAlchemy async), Neo4j, ChromaDB, Redis (Upstash-compatible)
- **Connectors**: All live in `apps/api/ingestion/connectors/` and extend `BaseConnector`
- **Scheduler**: `GOEScheduler` in `apps/api/ingestion/scheduler.py` — registers connectors and runs them via `IntervalTrigger`
- **Signal pipeline**: Every connector returns `list[dict]` → `GOEIntelligenceEngine.process_signal()` → stored in PostgreSQL + ChromaDB + Neo4j → published to Redis pub/sub → forwarded to WebSocket clients
- **BaseConnector pattern**: Each connector has `SOURCE_NAME`, `POLL_INTERVAL_SECONDS`, `CACHE_TTL_SECONDS`. The `run()` method checks Redis for last-fetch time, skips if within interval, calls `fetch()` / `parse()`, caches result in `goe:cache:{SOURCE_NAME}`, and records health in `goe:source_health:{SOURCE_NAME}`
- **Config**: `apps/api/config.py` uses `pydantic_settings` reading from `.env`
- **`std_signal()` helper**: Available on every connector — use it to build normalized signal dicts with `id`, `title`, `summary`, `domain`, `severity`, `india_score`, `source_url`, `published_at`, `raw`, `tags`

---

## YOUR TASK

Implement **all** of the feed integrations listed below into the GOE platform. For **each integration**, you must:

1. Create a new connector file in `apps/api/ingestion/connectors/`
2. Follow the exact `BaseConnector` interface (extend it, set `SOURCE_NAME`, `POLL_INTERVAL_SECONDS`, `CACHE_TTL_SECONDS`, implement `fetch()` and `parse()`)
3. Use the **exact same poll interval and cache TTL** as worldmonitor.app uses for that source (specified per-feed below)
4. Add every new connector to the `connector_list` in `GOEScheduler.__init__()` in `scheduler.py`
5. Add all required API keys / credentials to `apps/api/config.py` (as `Optional[str] = None`) and to `.env.example`
6. Use `self.std_signal()` to build normalized output wherever possible
7. Add per-feed circuit breaker behavior: if `fetch()` raises, `BaseConnector.run()` already catches and calls `_mark_error()` — do NOT swallow exceptions inside `fetch()` or `parse()`; let them bubble up
8. Cache stale data gracefully: if upstream is down, the cached Redis key `goe:cache:{SOURCE_NAME}` from the last successful run must remain usable by the API layer

---

## SECTION 1 — RSS / ATOM NEWS FEEDS (435+ sources)

### Architecture to implement

WorldMonitor uses **server-side feed aggregation** — all RSS feeds are batched server-side, not fetched per-client. You must replicate this pattern:

- Build a **`MassRSSAggregatorConnector`** that replaces (or extends) the current thin `RSSAggregatorConnector`
- Fetch **20 feeds concurrently** per batch using `asyncio.gather()` with a per-feed timeout of **8 seconds** and an overall deadline of **25 seconds**
- Cache the full digest in Redis under key `goe:digest:{variant}` with **TTL = 900 seconds (15 minutes)**
- Cache individual feed results under `goe:feed:{url_hash}` with **TTL = 600 seconds (10 minutes)**
- Cap items per feed at **5**, cap items per category at **20**
- Parse both RSS `<item>` and Atom `<entry>` formats using `feedparser`
- Assign each item a **source tier** (1–4) based on the list below, and include it in the signal's `tags` and `raw` fields
- Tag each item with a **propaganda_risk** flag for state-affiliated sources (RT, Xinhua, IRNA, CGTN, PressTV, Sputnik)
- `POLL_INTERVAL_SECONDS = 900` (15 minutes), `CACHE_TTL_SECONDS = 900`

### Feed list — implement ALL of the following, grouped by category

Each feed entry is: `(tier, source_name, url, category, domain)`

**TIER 1 — Wire Services & Official Government**
```
(1, "Reuters World",        "https://feeds.reuters.com/Reuters/worldNews",                        "wire",      "geopolitics")
(1, "Reuters Top News",     "https://feeds.reuters.com/reuters/topNews",                          "wire",      "geopolitics")
(1, "AP Top News",          "https://rsshub.app/ap/topics/apf-topnews",                           "wire",      "geopolitics")
(1, "AP World News",        "https://rsshub.app/ap/topics/apf-worldnews",                         "wire",      "geopolitics")
(1, "AFP World",            "https://www.afp.com/en/news-hub/rss",                                "wire",      "geopolitics")
(1, "BBC World",            "https://feeds.bbci.co.uk/news/world/rss.xml",                        "wire",      "geopolitics")
(1, "BBC News Top",         "https://feeds.bbci.co.uk/news/rss.xml",                              "wire",      "geopolitics")
(1, "US DOD",               "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?max=10",   "gov",       "defense")
(1, "US State Dept",        "https://www.state.gov/rss-feeds/press-releases/",                    "gov",       "geopolitics")
(1, "White House",          "https://www.whitehouse.gov/feed/",                                   "gov",       "geopolitics")
(1, "NATO",                 "https://www.nato.int/cps/en/natohq/news_rss.xml",                    "gov",       "defense")
(1, "UN News",              "https://news.un.org/feed/subscribe/en/news/all/rss.xml",              "gov",       "geopolitics")
(1, "EU Council",           "https://www.consilium.europa.eu/en/press/press-releases/rss/",       "gov",       "geopolitics")
```

**TIER 2 — Major Established Outlets**
```
(2, "CNN World",            "http://rss.cnn.com/rss/edition_world.rss",                           "mainstream","geopolitics")
(2, "NYT World",            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",             "mainstream","geopolitics")
(2, "The Guardian World",   "https://www.theguardian.com/world/rss",                              "mainstream","geopolitics")
(2, "Al Jazeera",           "https://www.aljazeera.com/xml/rss/all.xml",                          "mainstream","geopolitics")
(2, "Bloomberg",            "https://feeds.bloomberg.com/markets/news.rss",                       "markets",   "economics")
(2, "Financial Times",      "https://www.ft.com/?format=rss",                                    "markets",   "economics")
(2, "CNBC",                 "https://www.cnbc.com/id/100727362/device/rss/rss.html",              "markets",   "economics")
(2, "NPR World",            "https://feeds.npr.org/1004/rss.xml",                                 "mainstream","geopolitics")
(2, "France24",             "https://www.france24.com/en/rss",                                    "mainstream","geopolitics")
(2, "DW News",              "https://rss.dw.com/rdf/rss-en-all",                                  "mainstream","geopolitics")
(2, "Sky News",             "https://feeds.skynews.com/feeds/rss/world.xml",                      "mainstream","geopolitics")
(2, "Politico",             "https://www.politico.com/rss/politics08.xml",                        "mainstream","geopolitics")
(2, "Foreign Policy",       "https://foreignpolicy.com/feed/",                                    "intel",     "geopolitics")
(2, "The Economist",        "https://www.economist.com/latest/rss.xml",                           "mainstream","economics")
(2, "WSJ World",            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                       "markets",   "economics")
```

**TIER 3 — Defense / Intel / OSINT Specialists**
```
(3, "Defense One",          "https://www.defenseone.com/rss/all/",                               "defense",   "defense")
(3, "Breaking Defense",     "https://breakingdefense.com/feed/",                                  "defense",   "defense")
(3, "The War Zone",         "https://www.thedrive.com/the-war-zone/feed",                        "defense",   "defense")
(3, "Bellingcat",           "https://www.bellingcat.com/feed/",                                   "intel",     "geopolitics")
(3, "Just Security",        "https://www.justsecurity.org/feed/",                                 "intel",     "geopolitics")
(3, "War on the Rocks",     "https://warontherocks.com/feed/",                                    "defense",   "defense")
(3, "ISW",                  "https://www.understandingwar.org/feed",                              "intel",     "defense")
(3, "RAND",                 "https://www.rand.org/blog.rss",                                      "intel",     "geopolitics")
(3, "CSIS",                 "https://www.csis.org/analysis/feed",                                "intel",     "geopolitics")
(3, "IISS",                 "https://www.iiss.org/feed",                                          "intel",     "defense")
(3, "Stimson Center",       "https://www.stimson.org/feed/",                                     "intel",     "geopolitics")
(3, "Cipher Brief",         "https://www.thecipherbrief.com/feed",                               "intel",     "geopolitics")
(3, "Krebs on Security",    "https://krebsonsecurity.com/feed/",                                  "cyber",     "technology")
(3, "Threat Post",          "https://threatpost.com/feed/",                                      "cyber",     "technology")
(3, "Dark Reading",         "https://www.darkreading.com/rss.xml",                               "cyber",     "technology")
(3, "CISA Alerts",          "https://www.cisa.gov/cybersecurity-advisories/all.xml",             "cyber",     "technology")
(3, "Wired",                "https://www.wired.com/feed/rss",                                    "tech",      "technology")
(3, "MIT Tech Review",      "https://www.technologyreview.com/feed/",                            "tech",      "technology")
(3, "Ars Technica",         "https://feeds.arstechnica.com/arstechnica/index",                   "tech",      "technology")
(3, "Hacker News",          "https://hnrss.org/frontpage",                                       "tech",      "technology")
```

**MENA Region**
```
(2, "Al-Monitor",           "https://www.al-monitor.com/rss",                                    "mena",      "geopolitics")
(2, "Middle East Eye",      "https://www.middleeasteye.net/rss",                                 "mena",      "geopolitics")
(2, "The National UAE",     "https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml","mena",   "geopolitics")
(2, "Arab News",            "https://www.arabnews.com/rss.xml",                                  "mena",      "geopolitics")
(2, "Jerusalem Post",       "https://www.jpost.com/Rss/RssFeedsHeadlines.aspx",                 "mena",      "geopolitics")
(2, "Haaretz",              "https://www.haaretz.com/cmlink/1.4",                               "mena",      "geopolitics")
(3, "Iran International",   "https://www.iranintl.com/en/rss",                                  "mena",      "geopolitics")
(3, "IRNA",                 "https://en.irna.ir/rss",                                           "mena",      "geopolitics")   # state-affiliated, flag
(3, "Asharq Al-Awsat",      "https://aawsat.com/rss",                                           "mena",      "geopolitics")
(3, "Gulf News",            "https://gulfnews.com/rss",                                          "mena",      "geopolitics")
```

**Africa**
```
(2, "AllAfrica",            "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",   "africa",    "geopolitics")
(3, "Premium Times Nigeria","https://www.premiumtimesng.com/feed",                              "africa",    "geopolitics")
(3, "Daily Maverick SA",    "https://www.dailymaverick.co.za/feed/",                            "africa",    "geopolitics")
(3, "The East African",     "https://www.theeastafrican.co.ke/rss",                             "africa",    "geopolitics")
(3, "Africa Confidential",  "https://www.africa-confidential.com/rss",                         "africa",    "geopolitics")
```

**Asia-Pacific**
```
(2, "South China Morning Post","https://www.scmp.com/rss/91/feed",                             "asia",      "geopolitics")
(2, "Nikkei Asia",          "https://asia.nikkei.com/rss/feed/nar",                             "asia",      "economics")
(2, "NHK World",            "https://www3.nhk.or.jp/nhkworld/en/news/feeds/",                  "asia",      "geopolitics")
(3, "The Diplomat",         "https://thediplomat.com/feed/",                                    "asia",      "geopolitics")
(3, "Asia Times",           "https://asiatimes.com/feed/",                                      "asia",      "geopolitics")
(3, "Yonhap Korea",         "https://en.yna.co.kr/RSS/news.xml",                               "asia",      "geopolitics")
(3, "Taiwan News",          "https://www.taiwannews.com.tw/en/rss",                             "asia",      "geopolitics")
(3, "Xinhua",               "http://www.xinhuanet.com/english/rss/worldrss.xml",                "asia",      "geopolitics")  # state-affiliated, flag
```

**Energy & Commodities**
```
(2, "Reuters Energy",       "https://feeds.reuters.com/reuters/energy",                         "energy",    "economics")
(3, "Oil Price",            "https://oilprice.com/rss/main",                                    "energy",    "economics")
(3, "Energy Monitor",       "https://www.energymonitor.ai/feed/",                               "energy",    "economics")
(3, "S&P Global Commodity", "https://www.spglobal.com/commodityinsights/en/rss-news",           "energy",    "economics")
(3, "Platts",               "https://www.spglobal.com/platts/en/news-research/latest-news/rss", "energy",    "economics")
```

**Health / Humanitarian**
```
(1, "WHO News",             "https://www.who.int/rss-feeds/news-english.xml",                   "health",    "health")
(1, "CDC Newsroom",         "https://tools.cdc.gov/podcasts/feeds/rss/cdc-newsroom.xml",        "health",    "health")
(2, "ECDC Updates",         "https://www.ecdc.europa.eu/en/news-events/rss",                    "health",    "health")
(2, "ReliefWeb",            "https://reliefweb.int/updates/rss.xml",                            "humanitarian","health")
(1, "ProMED Mail",          "https://promedmail.org/feed/",                                     "health",    "health")
(2, "OCHA",                 "https://www.unocha.org/rss.xml",                                   "humanitarian","health")
```

**Finance & Markets**
```
(2, "MarketWatch",          "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines","markets",  "economics")
(2, "Seeking Alpha",        "https://seekingalpha.com/market_currents.xml",                     "markets",   "economics")
(3, "Zero Hedge",           "https://feeds.feedburner.com/zerohedge/feed",                      "markets",   "economics")
(3, "Naked Capitalism",     "https://www.nakedcapitalism.com/feed",                             "markets",   "economics")
(2, "BIS Speeches",         "https://www.bis.org/doclist/speeches.rss",                         "markets",   "economics")
(1, "Federal Reserve",      "https://www.federalreserve.gov/feeds/press_monetary.xml",          "markets",   "economics")
(1, "IMF",                  "https://www.imf.org/en/News/RSS",                                  "markets",   "economics")
(1, "World Bank Blog",      "https://blogs.worldbank.org/en/rss.xml",                          "markets",   "economics")
```

**Climate & Environment**
```
(2, "NASA Earth",           "https://www.nasa.gov/rss/dyn/earth.rss",                          "climate",   "climate")
(2, "NOAA News",            "https://www.noaa.gov/news-features/feed",                          "climate",   "climate")
(3, "Carbon Brief",         "https://www.carbonbrief.org/feed",                                "climate",   "climate")
(3, "Climate Home News",    "https://www.climatechangenews.com/feed/",                          "climate",   "climate")
(2, "UNEP",                 "https://www.unep.org/rss.xml",                                     "climate",   "climate")
```

**India (English)**
```
(2, "The Hindu",            "https://www.thehindu.com/news/national/feeder/default.rss",        "india",     "geopolitics")
(2, "Times of India",       "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",       "india",     "geopolitics")
(2, "Hindustan Times",      "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",  "india",     "geopolitics")
(2, "NDTV India",           "https://feeds.feedburner.com/ndtvnews-india-news",                "india",     "geopolitics")
(2, "India Today",          "https://www.indiatoday.in/rss/home",                               "india",     "geopolitics")
(1, "PTI",                  "https://www.ptinews.com/rss/",                                     "india",     "geopolitics")
(1, "PIB India",            "https://pib.gov.in/RSS/RSS-English.xml",                           "india",     "geopolitics")
(2, "Indian Express",       "https://indianexpress.com/feed/",                                  "india",     "geopolitics")
(3, "The Wire",             "https://thewire.in/feed",                                          "india",     "geopolitics")
(3, "Scroll.in",            "https://scroll.in/feed",                                           "india",     "geopolitics")
(2, "Business Standard",    "https://www.business-standard.com/rss/latest.rss",                "india",     "economics")
(2, "Economic Times",       "https://economictimes.indiatimes.com/rssfeedstopstories.cms",     "india",     "economics")
(2, "Mint",                 "https://www.livemint.com/rss/news",                               "india",     "economics")
```

**State-affiliated sources — include but flag**
```
(4, "RT",      "https://www.rt.com/rss/",                            "state_media", "geopolitics")  # propaganda_risk=HIGH
(4, "Xinhua",  "http://www.xinhuanet.com/english/rss/worldrss.xml",  "state_media", "geopolitics")  # propaganda_risk=HIGH
(4, "IRNA",    "https://en.irna.ir/rss",                             "state_media", "geopolitics")  # propaganda_risk=HIGH
(4, "CGTN",    "https://www.cgtn.com/subscribe/rss/section/world.do","state_media", "geopolitics")  # propaganda_risk=HIGH
(4, "Sputnik", "https://sputniknews.com/export/rss2/archive/index.xml","state_media","geopolitics") # propaganda_risk=HIGH
```

### Implementation notes for `MassRSSAggregatorConnector`:

```python
SOURCE_NAME = "mass_rss_aggregator"
POLL_INTERVAL_SECONDS = 900   # 15 min — matches worldmonitor
CACHE_TTL_SECONDS = 900

# Use asyncio.gather with timeout per feed:
async def _fetch_one(self, name, url):
    try:
        async with asyncio.timeout(8.0):
            text = await self.fetch_text(url)
            return (name, text)
    except Exception:
        return (name, None)

# Tag every signal with:
{
  "source_tier": tier,
  "category": category,
  "propaganda_risk": "HIGH" if state_affiliated else "LOW",
  "state_affiliated": True/False
}
```

---

## SECTION 2 — GOVERNMENT TRAVEL ADVISORIES (RSS/Atom polled)

**File**: `apps/api/ingestion/connectors/gov_advisories.py`

```
SOURCE_NAME = "gov_advisories"
POLL_INTERVAL_SECONDS = 1800  # 30 min
CACHE_TTL_SECONDS = 1800
```

### Sources to poll — fetch ALL of these in a single connector:

**National government advisories (RSS/Atom)**
```
US State Dept:          https://travel.state.gov/content/travel/en/traveladvisories/RSS.xml
UK FCDO:                https://www.gov.uk/foreign-travel-advice.atom
Australia DFAT:         https://www.smartraveller.gov.au/sites/default/files/atom.xml
New Zealand MFAT:       https://www.safetravel.govt.nz/rss.xml
Canada DFATD:           https://travel.gc.ca/travelling/advisories.rss
```

**US Embassy country-specific alert feeds — fetch ALL 13:**
```
Thailand:               https://th.usembassy.gov/feed/
UAE:                    https://ae.usembassy.gov/feed/
Germany:                https://de.usembassy.gov/feed/
Ukraine:                https://ua.usembassy.gov/feed/
Mexico:                 https://mx.usembassy.gov/feed/
India:                  https://in.usembassy.gov/feed/
Pakistan:               https://pk.usembassy.gov/feed/
Colombia:               https://co.usembassy.gov/feed/
Poland:                 https://pl.usembassy.gov/feed/
Bangladesh:             https://bd.usembassy.gov/feed/
Italy:                  https://it.usembassy.gov/feed/
Dominican Republic:     https://do.usembassy.gov/feed/
Myanmar:                https://mm.usembassy.gov/feed/
```

**Health agency feeds:**
```
CDC Travel Notices:     https://tools.cdc.gov/api/v2/resources/media/316422.rss
ECDC Epidemiology:      https://www.ecdc.europa.eu/en/news-events/rss
WHO News:               https://www.who.int/rss-feeds/news-english.xml
WHO Africa Emergencies: https://www.afro.who.int/rss.xml
```

### Advisory level parsing:
Parse advisory text for these levels and include as `advisory_level` in `raw` dict:
- `do_not_travel` → severity = 90, india_score boost +15 if India/Pakistan/Bangladesh
- `reconsider_travel` → severity = 70
- `exercise_increased_caution` → severity = 50
- `exercise_normal_precautions` → severity = 20

### Signal output format:
```python
self.std_signal(
    id=f"advisory-{source}-{country_code}-{date}",
    title=entry.title,
    summary=entry.summary,
    domain="geopolitics",
    severity=<derived from level>,
    india_score=<15 if India/neighbors, else 5>,
    url=entry.link,
    raw={"advisory_level": level, "issuing_gov": source, "country": country_code},
    tags=["advisory", source.lower(), country_code]
)
```

---

## SECTION 3 — CYBERSECURITY IOC FEEDS (6 feeds)

**File**: `apps/api/ingestion/connectors/cyber_ioc.py`

```
SOURCE_NAME = "cyber_ioc_feeds"
POLL_INTERVAL_SECONDS = 600   # 10 min — matches worldmonitor
CACHE_TTL_SECONDS = 600
MAX_IOC_DISPLAY = 500
ROLLING_WINDOW_DAYS = 14
```

### Feeds to implement:

| Feed | URL | IOC Type | Format |
|---|---|---|---|
| Feodo Tracker (abuse.ch) | `https://feodotracker.abuse.ch/downloads/ipblocklist.json` | C2 servers | JSON |
| URLhaus (abuse.ch) | `https://urlhaus-api.abuse.ch/v1/urls/recent/` | Malware hosts | JSON |
| C2IntelFeeds | `https://raw.githubusercontent.com/drb-ra/C2IntelFeeds/master/feeds/IPC2s.csv` | C2 servers | CSV |
| AlienVault OTX | `https://otx.alienvault.com/api/v1/pulses/subscribed` (requires API key) | Mixed IOCs | JSON |
| AbuseIPDB (check endpoint) | `https://api.abuseipdb.com/api/v2/blacklist` (requires API key) | Malicious IPs | JSON |
| Ransomware.live | `https://api.ransomware.live/recentvictims` | Ransomware victims | JSON |

### Config additions needed:
```python
ALIENVAULT_OTX_KEY: Optional[str] = None
ABUSEIPDB_API_KEY: Optional[str] = None
```

### Geo-enrichment:
- For each IP-based IOC, call `https://ipinfo.io/{ip}/json` to get lat/lon/country
- Fallback: `https://freeipapi.com/api/json/{ip}`
- Run **16 parallel geo-enrichment requests** with `asyncio.gather()`
- Cache geo results per IP in Redis: key `goe:geo:{ip}`, TTL = **86400 seconds (24h)**
- Cap at **250 IPs per collection run** for enrichment
- Only show most recent 500 IOCs (trim after enrichment)

### IOC type classification:
```python
IOC_TYPE_MAP = {
    "feodo":       "c2_server",
    "urlhaus":     "malware_host",
    "c2intel":     "c2_server",
    "alienvault":  "mixed",
    "abuseipdb":   "malicious_ip",
    "ransomware":  "ransomware"
}
```

### Signal output includes:
```python
{
  "ioc_type": "c2_server",
  "ioc_value": "1.2.3.4",
  "ioc_source": "feodo_tracker",
  "latitude": ...,
  "longitude": ...,
  "country": "RU",
  "tags": ["cyber", "ioc", "c2_server"]
}
```

---

## SECTION 4 — NATURAL DISASTERS (3 sources, merge + deduplicate)

**File**: `apps/api/ingestion/connectors/natural_disasters.py`

This connector merges USGS, GDACS, and NASA EONET into a single deduplicated stream.

```
SOURCE_NAME = "natural_disasters"
POLL_INTERVAL_SECONDS = 300   # 5 min — matches worldmonitor USGS cadence
CACHE_TTL_SECONDS = 300
```

### Sub-sources:

**USGS Earthquakes** (already in project as separate connector — merge it here or keep separate)
- URL: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_hour.geojson`
- Filter: M4.5+
- Dedup key: `usgs-{feature_id}`

**GDACS (UN Disaster Alerts)**
- URL: `https://www.gdacs.org/xml/rss.xml`
- Types: Earthquakes, floods, cyclones, volcanoes, wildfires, droughts
- Filter: exclude Green/Low severity alerts (keep Orange + Red only)
- Severity mapping: Red → 85, Orange → 65, Green → skip
- Parse as RSS feed using feedparser

**NASA EONET (Earth Observing System Events)**
- URL: `https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30`
- Types: All 13 natural event categories
- Filter: Wildfires only if within last 48 hours
- Exclude earthquakes (USGS provides better quality)

### Deduplication logic:
- Use **Haversine distance** on a 0.1° grid (~11km) with same-day matching
- If two events from different sources are within 0.1° and same calendar day, keep the one with highest source priority: USGS > GDACS > EONET
- Store dedup keys in Redis set `goe:disaster_dedup:{date}` with TTL = 86400s

```python
def haversine_key(lat: float, lon: float, precision: float = 0.1) -> str:
    return f"{round(lat / precision) * precision:.1f}_{round(lon / precision) * precision:.1f}"
```

---

## SECTION 5 — NASA FIRMS SATELLITE FIRE DETECTION

The project already has `NASAFirmsConnector`. Upgrade it:

```
SOURCE_NAME = "nasa_firms"
POLL_INTERVAL_SECONDS = 1800  # 30 min — matches worldmonitor
CACHE_TTL_SECONDS = 1800
```

**Changes to make**:
1. Fetch **VIIRS_SNPP_NRT** (Near Real Time) data for the **entire world**, not just 1 day — use `days=1` parameter
2. Also fetch **MODIS_NRT** as a second pass for cross-validation: `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/MODIS_NRT/world/1`
3. Parse CSV properly: columns are `latitude, longitude, bright_t31, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight`
4. Filter: Only include entries where `confidence >= 50` (medium/high confidence)
5. Compute severity from Fire Radiative Power (FRP): `severity = min(100, int(frp / 10))` where FRP column is available
6. Tag with `daynight` field

---

## SECTION 6 — CLIMATE ANOMALY DETECTION (Open-Meteo ERA5)

**File**: `apps/api/ingestion/connectors/climate_anomalies.py`

```
SOURCE_NAME = "climate_anomalies"
POLL_INTERVAL_SECONDS = 3600  # 1 hour
CACHE_TTL_SECONDS = 3600
```

### 15 monitored zones:
```python
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
```

### API call for each zone:
```
https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}
  &daily=temperature_2m_max,precipitation_sum
  &past_days=30
  &forecast_days=1
  &timezone=UTC
```

### Anomaly scoring:
```
Temperature deviation > 5°C above 30-day mean → severity = 80 (EXTREME)
Temperature deviation > 3°C above 30-day mean → severity = 55 (MODERATE)
Precipitation deviation > 80mm/day above mean  → severity = 80 (EXTREME)
Precipitation deviation > 40mm/day above mean  → severity = 55 (MODERATE)
Otherwise → skip (no signal emitted)
```

---

## SECTION 7 — AVIATION DELAYS / NOTAMs (3 sources)

**File**: `apps/api/ingestion/connectors/aviation_delays.py`

```
SOURCE_NAME = "aviation_delays"
POLL_INTERVAL_SECONDS = 300   # 5 min — matches worldmonitor
CACHE_TTL_SECONDS = 1800      # 30 min cache
```

### Config additions:
```python
AVIATIONSTACK_API_KEY: Optional[str] = None
ICAO_API_KEY: Optional[str] = None
```

### Sub-source 1 — FAA ASWS (14 US airports, free XML feed):
```
URL: https://nasstatus.faa.gov/api/airport-status-information
Method: GET, returns XML
Parse: ground delays, ground stops, arrival delays, closures
```

**14 monitored US airports**: ATL, LAX, ORD, DFW, DEN, SFO, SEA, LAS, MCO, EWR, JFK, LGA, BOS, MIA

### Sub-source 2 — AviationStack (40 international airports, API key required):
```
URL: http://api.aviationstack.com/v1/flights
Params: access_key={key}, dep_icao={airport}, limit=100
```

**40 international airports** (ICAO codes): EGLL, EDDF, LFPG, LIRF, LEMD, EHAM, LSZH, OMDB, OTHH, OBBI, OJAM, LLBG, LTFM, VVTS, WSSS, VTBS, VIDP, VOBL, RJTT, RKSI, ZSSS, ZBAA, VHHH, YSSY, YMML, FAOR, HAAB, DNMM, DIAP, HECA

**Severity thresholds** (from delay duration):
```python
delay_minutes >= 60 or cancel_rate >= 60% → "severe"
delay_minutes >= 45 or cancel_rate >= 45% → "major"
delay_minutes >= 30 or cancel_rate >= 30% → "moderate"
delay_minutes >= 15 or cancel_rate >= 15% → "minor"
```

### Sub-source 3 — ICAO NOTAM (46 MENA airports):
```
URL: https://applications.icao.int/dataservices/api/notams?api_key={key}&icaos={codes}&format=json
```

**46 MENA airports**: OMDB, OBBI, OTHH, OEDF, OEJN, LLBG, OJAM, OSDI, LTFM, LTAC, HECA, HESH, VIDF, VIDP, OPKC, OPLA, OJAI, OKBK, OMAA, OMSJ, ORMM, ORBI, OBIC, OIIE, OIKB, OIKK, OISS, OIZH, OISL, OIFS, OIFM, OIAW, OICC, OIGG, OITT, OITR, OIAH, OIZB, OIZI, OIKE, OIKR, OIBS, OIBP, OIBL, OIBK, OIBH

**NOTAM closure detection**:
```python
CLOSURE_CODES = ["FA", "AH", "AL", "AW", "AC", "AM"]
CLOSURE_KEYWORDS = ["AD CLSD", "AIRPORT CLOSED", "AIRSPACE CLOSED", "CLSD TO", "CLOSED"]
```

---

## SECTION 8 — INTERNET OUTAGES (Cloudflare Radar)

**File**: `apps/api/ingestion/connectors/internet_outages.py`

```
SOURCE_NAME = "cloudflare_radar"
POLL_INTERVAL_SECONDS = 300   # 5 min
CACHE_TTL_SECONDS = 300
```

### Config addition:
```python
CLOUDFLARE_API_TOKEN: Optional[str] = None
```

### API endpoints:
```
Internet Quality:   https://api.cloudflare.com/client/v4/radar/quality/iqi/summary
Outage Summary:     https://api.cloudflare.com/client/v4/radar/traffic/anomalies/locations
BGP Anomalies:      https://api.cloudflare.com/client/v4/radar/bgp/route-moas/summary
```

Headers: `Authorization: Bearer {CLOUDFLARE_API_TOKEN}`

Parse: locations with traffic drop > 30% relative to 7-day baseline → emit as signal with severity proportional to traffic drop percentage.

---

## SECTION 9 — GPS JAMMING (gpsjam.org)

**File**: `apps/api/ingestion/connectors/gps_jamming.py`

```
SOURCE_NAME = "gps_jamming"
POLL_INTERVAL_SECONDS = 3600  # 1 hour
CACHE_TTL_SECONDS = 3600
```

### Fetch:
```
URL: https://gpsjam.org/about  # scrape the API or use:
URL: https://gpsjam.org/api/latest  # returns H3 hexagonal grid cells as JSON
```

Each cell has: `h3_index`, `bad_percent` (% of aircraft reporting GPS anomalies), `total_aircraft`

### Classification:
```python
if bad_percent > 10:   # >10% bad → HIGH interference
    severity = 75
elif bad_percent > 2:  # 2-10% bad → MEDIUM
    severity = 45
else:
    continue           # skip LOW (< 2%)

# Minimum 3 aircraft per cell to be statistically valid
if total_aircraft < 3:
    continue
```

### Region tagging — tag each hex cell to one of these 12 regions:
```python
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
```

Convert H3 hex index centroid (use `h3` Python library: `pip install h3`) to lat/lon for region tagging.

---

## SECTION 10 — FINANCIAL MARKETS (multi-source)

Extend/replace the existing `YahooFinanceConnector` and `CoinGeckoConnector`, and add new connectors:

### 10a — Yahoo Finance (upgrade existing)
**File**: `apps/api/ingestion/connectors/yahoo_finance.py` (upgrade)

```
SOURCE_NAME = "yahoo_finance"
POLL_INTERVAL_SECONDS = 300   # 5 min polling, 8 min cache (matches worldmonitor GCC panel)
CACHE_TTL_SECONDS = 480       # 8 min
```

**Expand symbols list to include**:
```python
EQUITY_SYMBOLS = ["^NSEI", "^BSESN", "^GSPC", "^DJI", "^IXIC", "^FTSE", "^GDAXI", "^FCHI", "^N225", "000001.SS", "^HSI"]
COMMODITY_SYMBOLS = ["GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "ZW=F", "ZS=F"]
FOREX_SYMBOLS = ["INR=X", "EURUSD=X", "GBPUSD=X", "JPY=X", "CNY=X", "SAR=X", "AED=X"]
GCC_INDICES = ["^TASI.SR", "^DFMGI.AE", "^ADI.AE", "^QSI.QA", "^MSM30.OM"]
ETF_SYMBOLS = ["IBIT", "FBTC", "GBTC", "ARKB", "HODL"]   # BTC spot ETFs
```

Use **staggered batching** — fetch 5 symbols per batch with a 200ms delay between batches to avoid rate limiting.

### 10b — CoinGecko (upgrade existing)
**File**: `apps/api/ingestion/connectors/coingecko.py` (upgrade)

```
SOURCE_NAME = "coingecko_markets"
POLL_INTERVAL_SECONDS = 300   # 5 min
CACHE_TTL_SECONDS = 300
```

Fetch:
1. `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin,ethereum,solana,ripple,tether,usd-coin,dai` — full price data
2. `https://api.coingecko.com/api/v3/search/trending` — trending assets
3. `https://api.coingecko.com/api/v3/global` — global market stats

Include: Fear & Greed via `https://api.alternative.me/fng/?limit=30` (30-day history)
Include: BTC hash rate via `https://mempool.space/api/v1/mining/hashrate/pools/1m`

### 10c — FRED Economic Data (upgrade existing `WorldBankConnector` or new)
**File**: `apps/api/ingestion/connectors/fred_economic.py`

```
SOURCE_NAME = "fred_economic"
POLL_INTERVAL_SECONDS = 3600  # 1 hour (macro data doesn't change faster)
CACHE_TTL_SECONDS = 3600
```

Config: `FRED_API_KEY: Optional[str] = None`

Series to fetch (one API call each):
```python
FRED_SERIES = {
    "GDP":          "GDP",         # US GDP
    "INFLATION":    "CPIAUCSL",    # US CPI
    "FED_RATE":     "FEDFUNDS",    # Federal Funds Rate
    "UNEMPLOYMENT": "UNRATE",      # US Unemployment
    "DXY":          "DTWEXBGS",    # US Dollar Index
    "10Y_YIELD":    "DGS10",       # 10-Year Treasury
    "VIX":          "VIXCLS",      # Volatility Index
    "WTI_CRUDE":    "DCOILWTICO",  # WTI Crude Oil Price
}
```

URL pattern: `https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={key}&limit=5&sort_order=desc&file_type=json`

### 10d — EIA Energy Data
**File**: `apps/api/ingestion/connectors/eia_energy.py`

```
SOURCE_NAME = "eia_energy"
POLL_INTERVAL_SECONDS = 3600
CACHE_TTL_SECONDS = 3600
```

Config: `EIA_API_KEY: Optional[str] = None`

Endpoints:
```
WTI Price:     https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key={key}&data[]=value&frequency=daily&sort[0][column]=period&sort[0][direction]=desc&length=5
Natural Gas:   https://api.eia.gov/v2/natural-gas/pri/sum/data/?api_key={key}&data[]=value&frequency=monthly&length=3
```

### 10e — Polymarket Prediction Markets
**File**: `apps/api/ingestion/connectors/polymarket.py`

```
SOURCE_NAME = "polymarket_predictions"
POLL_INTERVAL_SECONDS = 300   # 5 min
CACHE_TTL_SECONDS = 300
```

```
URL: https://gamma-api.polymarket.com/markets?closed=false&limit=50&tag=politics
URL: https://gamma-api.polymarket.com/markets?closed=false&limit=50&tag=world
URL: https://gamma-api.polymarket.com/markets?closed=false&limit=50&tag=ukraine
```

**Note**: Polymarket blocks server-side requests via Cloudflare JA3 fingerprinting. Implement a retry with random `User-Agent` rotation. If all attempts fail within the connector, return cached data silently.

Filter markets: exclude sports/entertainment (keywords: NBA, NFL, Oscar, Grammy, Super Bowl, World Cup). Only include markets with volume > $50,000 or probability divergence from 50% by > 15 percentage points.

### 10f — BIS Central Bank Data
**File**: `apps/api/ingestion/connectors/bis_data.py`

```
SOURCE_NAME = "bis_central_banks"
POLL_INTERVAL_SECONDS = 86400   # Daily (data updates infrequently)
CACHE_TTL_SECONDS = 86400
```

```
Policy rates:  https://data.bis.org/topics/SPE/BIS,WS_SPE,1.0/all?format=json
REER:          https://data.bis.org/topics/EER/BIS,WS_EER,1.0/all?format=json
```

### 10g — WTO Trade Policy
**File**: `apps/api/ingestion/connectors/wto_trade.py`

```
SOURCE_NAME = "wto_trade"
POLL_INTERVAL_SECONDS = 3600
CACHE_TTL_SECONDS = 3600
```

```
URL: https://www.wto.org/english/news_e/news_e_rss_en.xml   # WTO news RSS
URL: https://tpr.wto.org/en/feed                             # Trade Policy Review RSS
```

---

## SECTION 11 — HUMANITARIAN DATA (HAPI, UNHCR, WorldPop)

**File**: `apps/api/ingestion/connectors/humanitarian.py`

```
SOURCE_NAME = "humanitarian_data"
POLL_INTERVAL_SECONDS = 3600   # 1 hour
CACHE_TTL_SECONDS = 3600
```

### Sub-sources:

**UN OCHA HAPI (Humanitarian API)**:
```
URL: https://hapi.humdata.org/api/v1/population/refugee?output_format=json&limit=100
URL: https://hapi.humdata.org/api/v1/population/idps?output_format=json&limit=100
Headers: X-HDX-HAPI-APP-IDENTIFIER: {your app id}
```

Extract: `origin_iso3`, `asylum_iso3`, `population` for refugee flows.
Threshold signals: > 1,000,000 displaced → severity=80; > 500,000 → severity=60.

**UNHCR Population Statistics**:
```
URL: https://api.unhcr.org/population/v1/population/?limit=20&sortBy=total&sortOrder=desc
```

**ReliefWeb Disaster Reports** (upgrade existing connector):
```
URL: https://api.reliefweb.int/v1/reports?appname=goe&fields[include][]=title,body,date&filter[field]=type.name&filter[value]=Situation+Report&limit=20
```

**WorldPop Population Density** (for event exposure estimation):
- Not a polling feed — call on-demand when a new high-severity event is processed
- Store as utility function: `get_population_exposure(lat, lon, radius_km)`
- URL: `https://api.worldpop.org/v1/services/stats?dataset=wpgp&year=2020&geojson={polygon}`
- Only call for events with severity >= 70

---

## SECTION 12 — OREF ROCKET ALERTS (Israel Home Front Command)

**File**: `apps/api/ingestion/connectors/oref_alerts.py`

```
SOURCE_NAME = "oref_rocket_alerts"
POLL_INTERVAL_SECONDS = 300   # 5 min — matches worldmonitor
CACHE_TTL_SECONDS = 60        # short cache; this is near-real-time
```

### Implementation notes:
The OREF site (`https://www.oref.org.il/WarningMessages/alert/alerts.json`) is **WAF-protected by Akamai**. Standard `httpx` requests are JA3-blocked. Implement the following strategies in priority order:

**Strategy 1 — Custom headers to mimic browser TLS**:
```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://www.oref.org.il/12481-he/Pakar.aspx",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="122"',
    "sec-fetch-site": "same-origin",
}
```

**Strategy 2 — Unofficial community mirror** (more reliable):
```
URL: https://api.tzevaadom.co.il/notifications   # community mirror of OREF
URL: https://red-alert.space/api/v1/alerts       # alternative mirror
```

**Strategy 3 — If configured, route through a residential proxy**:
```python
OREF_PROXY_URL: Optional[str] = None  # Add to config.py
# Example: "http://user:pass@residential-proxy.example.com:8080"
```

### Alert parsing:
```python
# OREF response format: {"id":"...", "cat":"1", "title":"ירי רקטות וטילים", "data":["Tel Aviv","Hadera"], "desc":"..."}
# cat values: 1=rockets, 2=hostile_aircraft, 3=earthquake, 4=radiological, 6=tsunami, 7=hostile_fire

ALERT_TYPE_MAP = {
    "1": "rockets_missiles",
    "2": "hostile_aircraft",
    "3": "earthquake",
    "4": "radiological",
    "6": "tsunami",
    "7": "hostile_fire"
}
```

### Hebrew→English translation:
Store a dictionary of 1,480 Hebrew city names mapped to English. This should be loaded from a JSON file `apps/api/data/oref_cities_he_en.json`. Bootstrap it by fetching:
```
https://raw.githubusercontent.com/hasadna/open-bus-gtfs-etl/master/output/cities.json
```
at startup if the file doesn't exist.

### Signal output:
```python
self.std_signal(
    id=f"oref-{alert['id']}-{datetime.now().date()}",
    title=f"OREF Alert: {ALERT_TYPE_MAP[alert['cat']]} — {', '.join(english_locations[:3])}",
    summary=f"Active alert in: {', '.join(english_locations)}",
    domain="defense",
    severity=90,
    india_score=5,   # regional significance
    latitude=31.5,   # Israel centroid
    longitude=34.9,
    raw={"alert_type": cat, "locations": english_locations, "hebrew_locations": alert["data"]},
    tags=["oref", "rocket_alert", "israel", ALERT_TYPE_MAP[alert["cat"]]]
)
```

**Wave detection**: Group alerts within a 10-minute sliding window. If 3+ alerts in the window, emit a "multi-wave barrage" signal with severity=95.

---

## SECTION 13 — IRAN CONFLICT EVENTS (LiveUAMap)

**File**: `apps/api/ingestion/connectors/iran_liveuamap.py`

```
SOURCE_NAME = "iran_liveuamap"
POLL_INTERVAL_SECONDS = 300   # 5 min
CACHE_TTL_SECONDS = 300
```

LiveUAMap does not have an official public API. Implement the following approach:

**Option A — RSS feed** (preferred if available):
```
https://liveuamap.com/en/iran/rss
https://liveuamap.com/en/israel/rss
```

**Option B — HTML scraping with minimal parsing**:
Fetch `https://liveuamap.com/en/isr` and extract event data from the JSON embedded in the page's `<script>` tags (they embed initial state as `window.__initialState__`).

**Option C — GDELT as proxy**:
```python
GDELT_IRAN_URL = "https://api.gdeltproject.org/api/v2/doc/doc?query=Iran+attack+OR+Iran+strike+OR+Iran+military&mode=ArtList&format=json&maxrecords=15&TIMESPAN=1440"
```

Implement all three with fallback chain: Option A → Option B → Option C.

Signal domain: `"defense"`, severity: 65–90 depending on keywords (strike=85, attack=80, exchange=75, incident=65).

---

## SECTION 14 — GDELT FULL INTEGRATION (upgrade existing)

The existing `GDELTConnector` only queries India/South Asia. Expand it:

**File**: `apps/api/ingestion/connectors/gdelt.py` (upgrade)

```
SOURCE_NAME = "gdelt_events"
POLL_INTERVAL_SECONDS = 600   # 10 min — matches worldmonitor
CACHE_TTL_SECONDS = 600
```

Fetch **multiple themed queries** concurrently:
```python
GDELT_QUERIES = [
    ("global_conflict",  "conflict OR war OR military operation", "defense"),
    ("protests",         "protest OR demonstration OR riot OR unrest", "geopolitics"),
    ("disaster",         "earthquake OR flood OR cyclone OR wildfire disaster", "climate"),
    ("cyber",            "cyberattack OR ransomware OR data breach", "technology"),
    ("economics",        "sanctions OR tariff OR trade war OR economic crisis", "economics"),
    ("health",           "outbreak OR pandemic OR epidemic disease", "health"),
    ("india_focus",      "India OR South Asia OR Modi OR Pakistan", "geopolitics"),
]
```

URL pattern for each:
```
https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=ArtList&format=json&maxrecords=20&TIMESPAN=1440
```

Use GDELT Doc API v2 `tone` field to set severity: tone < -5 → severity=70; tone < -2 → severity=50; else severity=35.

Also fetch **GDELT GEO2 geospatial events** for protest deduplication layer:
```
https://api.gdeltproject.org/api/v2/geo/geo?query={query}&mode=pointdata&format=json
```

---

## SECTION 15 — WHO / CDC HEALTH FEEDS (upgrade existing)

The existing `WHOConnector` is minimal. Expand it substantially:

**File**: `apps/api/ingestion/connectors/health_feeds.py` (new, replaces who.py)

```
SOURCE_NAME = "global_health_feeds"
POLL_INTERVAL_SECONDS = 1800  # 30 min
CACHE_TTL_SECONDS = 1800
```

Fetch ALL of these:
```python
HEALTH_FEEDS = [
    ("WHO Global News",         "https://www.who.int/rss-feeds/news-english.xml"),
    ("WHO Africa Emergencies",  "https://www.afro.who.int/rss.xml"),
    ("WHO PAHO Americas",       "https://www.paho.org/en/rss.xml"),
    ("WHO SEARO Asia",          "https://www.who.int/southeastasia/rss-feeds"),
    ("CDC Newsroom",            "https://tools.cdc.gov/podcasts/feeds/rss/cdc-newsroom.xml"),
    ("CDC Health Alert Network","https://emergency.cdc.gov/han/feed/han_feed.xml"),
    ("CDC Travel Health",       "https://wwwnc.cdc.gov/travel/rss"),
    ("ECDC Communicable Disease","https://www.ecdc.europa.eu/en/news-events/rss"),
    ("ProMED Mail",             "https://promedmail.org/feed/"),
    ("OCHA Humanitarian",       "https://www.unocha.org/rss.xml"),
    ("MSF Doctors Without Borders","https://www.msf.org/feed"),
    ("IFRC Red Cross",          "https://www.ifrc.org/rss"),
    ("Outbreak News Today",     "https://outbreaknewstoday.com/feed/"),
    ("Health Map",              "https://www.healthmap.org/rss/en/rss.xml"),
    ("GOARN Alerts",            "https://extranet.who.int/goarn/sites/default/files/goarn_feed.xml"),
]
```

**Keyword-based severity escalation** for health signals:
```python
HEALTH_SEVERITY_KEYWORDS = {
    90: ["pandemic", "global health emergency", "PHEIC"],
    80: ["outbreak", "epidemic", "emergency declaration"],
    65: ["unusual disease", "novel pathogen", "unknown illness"],
    50: ["alert", "warning", "increased incidence"],
    35: ["surveillance", "monitoring", "update"]
}
```

---

## SECTION 16 — LIVE VIDEO STREAM CATALOG (metadata only, no actual streaming)

**File**: `apps/api/ingestion/connectors/live_streams.py`

```
SOURCE_NAME = "live_stream_catalog"
POLL_INTERVAL_SECONDS = 3600  # 1 hour — just validate streams are still live
CACHE_TTL_SECONDS = 3600
```

This connector doesn't process news — it maintains a **health-checked catalog** of live video streams that your frontend can embed. For each stream, perform an HTTP HEAD request to validate the stream URL is accessible and emit a signal only if a stream goes offline or comes back online.

```python
LIVE_STREAMS = [
    # HLS native streams
    {"name": "Bloomberg TV",       "url": "https://bloombergtv.akamaized.net/...", "type": "hls",     "region": "global",   "category": "markets"},
    {"name": "Al Jazeera English", "url": "https://aljazeera-eng-hd-live.akamaized.net/...", "type": "hls", "region": "mena", "category": "news"},
    {"name": "Sky News",           "url": "https://skynews-app-cdn.akamaized.net/...", "type": "hls", "region": "europe",  "category": "news"},
    {"name": "CGTN",               "url": "https://news.cgtn.com/resource/live/english/cgtn-news.m3u8", "type": "hls", "region": "asia", "category": "news"},
    {"name": "France24 EN",        "url": "https://static.france24.com/live/F24_EN_HI_HLS/live_web.m3u8", "type": "hls", "region": "europe", "category": "news"},
    {"name": "DW News",            "url": "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8", "type": "hls", "region": "europe", "category": "news"},
    {"name": "NDTV 24x7",          "url": "https://ndtvstream.akamaized.net/...", "type": "hls", "region": "india", "category": "news"},
    {"name": "Republic TV",        "url": "https://republicworld-livepkgr.akamaized.net/...", "type": "hls", "region": "india", "category": "news"},
    # YouTube embeds (store YouTube video IDs)
    {"name": "Jerusalem Webcam",   "youtube_id": "oBTYEPCnkO4", "type": "youtube", "region": "mena",   "category": "surveillance", "lat": 31.7767, "lon": 35.2345},
    {"name": "Tehran Street",      "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "mena",   "category": "surveillance", "lat": 35.6892, "lon": 51.3890},
    {"name": "Kyiv Live",          "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "europe", "category": "surveillance", "lat": 50.4501, "lon": 30.5234},
    {"name": "Washington DC",      "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "americas","category": "surveillance", "lat": 38.8951, "lon": -77.0364},
    {"name": "New York Times Sq",  "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "americas","category": "surveillance", "lat": 40.7580, "lon": -73.9855},
    {"name": "Taipei City",        "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "asia",   "category": "surveillance", "lat": 25.0330, "lon": 121.5654},
    {"name": "Seoul Live",         "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "asia",   "category": "surveillance", "lat": 37.5665, "lon": 126.9780},
    {"name": "Shanghai Skyline",   "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "asia",   "category": "surveillance", "lat": 31.2304, "lon": 121.4737},
    {"name": "Mecca Grand Mosque", "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "mena",   "category": "surveillance", "lat": 21.4225, "lon": 39.8262},
    {"name": "London Eye",         "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "europe", "category": "surveillance", "lat": 51.5033, "lon": -0.1195},
    {"name": "Paris Eiffel",       "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "europe", "category": "surveillance", "lat": 48.8584, "lon": 2.2945},
    {"name": "Tokyo Shibuya",      "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "asia",   "category": "surveillance", "lat": 35.6598, "lon": 139.7006},
    {"name": "Sydney Harbour",     "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "asia",   "category": "surveillance", "lat": -33.8568, "lon": 151.2153},
    {"name": "Los Angeles",        "youtube_id": "CHANGE_ME",   "type": "youtube", "region": "americas","category": "surveillance", "lat": 34.0522, "lon": -118.2437},
]
```

Store the full catalog in Redis key `goe:live_streams` with TTL = 3600. Emit a signal only when a stream status changes (online → offline or vice versa).

---

## SECTION 17 — SCHEDULER REGISTRATION

After implementing all connectors, update `apps/api/ingestion/scheduler.py` to register them all:

```python
# Add ALL new imports:
from .connectors.mass_rss import MassRSSAggregatorConnector
from .connectors.gov_advisories import GovAdvisoryConnector
from .connectors.cyber_ioc import CyberIOCConnector
from .connectors.natural_disasters import NaturalDisasterConnector
from .connectors.climate_anomalies import ClimateAnomalyConnector
from .connectors.aviation_delays import AviationDelaysConnector
from .connectors.internet_outages import InternetOutagesConnector
from .connectors.gps_jamming import GPSJammingConnector
from .connectors.fred_economic import FREDEconomicConnector
from .connectors.eia_energy import EIAEnergyConnector
from .connectors.polymarket import PolymarketConnector
from .connectors.bis_data import BISDataConnector
from .connectors.wto_trade import WTOTradeConnector
from .connectors.humanitarian import HumanitarianConnector
from .connectors.oref_alerts import OREFAlertsConnector
from .connectors.iran_liveuamap import IranLiveUAMapConnector
from .connectors.health_feeds import GlobalHealthFeedsConnector
from .connectors.live_streams import LiveStreamCatalogConnector

# Add to connector_list in GOEScheduler.__init__:
connector_list = [
    USGSConnector(*args),
    NaturalDisasterConnector(*args),     # replaces/supplements USGSConnector
    GDELTConnector(*args),
    ACLEDConnector(*args),
    MassRSSAggregatorConnector(*args),   # replaces RSSAggregatorConnector
    GovAdvisoryConnector(*args),
    CyberIOCConnector(*args),
    ClimateAnomalyConnector(*args),
    AviationDelaysConnector(*args),
    InternetOutagesConnector(*args),
    GPSJammingConnector(*args),
    CoinGeckoConnector(*args),
    YahooFinanceConnector(*args),
    FREDEconomicConnector(*args),
    EIAEnergyConnector(*args),
    PolymarketConnector(*args),
    BISDataConnector(*args),
    WTOTradeConnector(*args),
    HumanitarianConnector(*args),
    OREFAlertsConnector(*args),
    IranLiveUAMapConnector(*args),
    GlobalHealthFeedsConnector(*args),
    LiveStreamCatalogConnector(*args),
    NASAFirmsConnector(*args),
    NOAAConnector(*args),
    WHOConnector(*args),
    ReliefWebConnector(*args),
    IAEAConnector(*args),
    OpenSkyConnector(*args),
    IndiaGovConnector(*args),
    WorldBankConnector(*args),
]
```

---

## SECTION 18 — CONFIG.PY ADDITIONS

Add ALL of these new settings to `apps/api/config.py`:

```python
# RSS & News
RSS_PROXY_ENABLED: bool = False
RSS_PROXY_URL: Optional[str] = None

# Government Advisories
ICAO_API_KEY: Optional[str] = None
AVIATIONSTACK_API_KEY: Optional[str] = None
FAA_ASWS_ENABLED: bool = True

# Cybersecurity
ALIENVAULT_OTX_KEY: Optional[str] = None
ABUSEIPDB_API_KEY: Optional[str] = None

# Financial
FRED_API_KEY: Optional[str] = None
EIA_API_KEY: Optional[str] = None
FINNHUB_API_KEY: Optional[str] = None
COINGECKO_API_KEY: Optional[str] = None  # optional, for higher rate limits

# Internet / GPS
CLOUDFLARE_API_TOKEN: Optional[str] = None

# Humanitarian
HAPI_APP_IDENTIFIER: Optional[str] = None
UNHCR_API_TOKEN: Optional[str] = None

# OREF
OREF_PROXY_URL: Optional[str] = None

# Polymarket
POLYMARKET_ENABLED: bool = True

# WTO / BIS
WTO_FEEDS_ENABLED: bool = True
BIS_FEEDS_ENABLED: bool = True

# Live Streams
LIVE_STREAMS_ENABLED: bool = True
```

---

## SECTION 19 — .env.example ADDITIONS

Add these to `.env.example`:
```dotenv
# ── New Feed Integrations ──────────────────────────────────────────────────
FRED_API_KEY=your_fred_api_key_from_fred.stlouisfed.org
EIA_API_KEY=your_eia_key_from_eia.gov
FINNHUB_API_KEY=your_finnhub_key
AVIATIONSTACK_API_KEY=your_aviationstack_key
ICAO_API_KEY=your_icao_key
CLOUDFLARE_API_TOKEN=your_cloudflare_radar_token
ALIENVAULT_OTX_KEY=your_otx_key_from_otx.alienvault.com
ABUSEIPDB_API_KEY=your_abuseipdb_key
HAPI_APP_IDENTIFIER=goe-intelligence-platform
OREF_PROXY_URL=   # Optional: http://user:pass@residential-proxy:8080
```

---

## SECTION 20 — REDIS KEY NAMING CONVENTION

All new connectors must follow this Redis key naming convention (already established in the codebase):

| Key Pattern | TTL | Purpose |
|---|---|---|
| `goe:last_fetch:{SOURCE_NAME}` | — | Timestamp of last successful fetch (float) |
| `goe:cache:{SOURCE_NAME}` | Per connector | Full JSON array of last successful items |
| `goe:source_health:{SOURCE_NAME}` | — | Hash: status, last_success, last_error, items_count, latency_ms |
| `goe:digest:{variant}` | 900s | Mass RSS aggregated digest |
| `goe:feed:{url_hash}` | 600s | Individual RSS feed cache |
| `goe:geo:{ip}` | 86400s | IP geolocation cache for IOCs |
| `goe:disaster_dedup:{date}` | 86400s | Haversine dedup set for disasters |
| `goe:live_streams` | 3600s | Live stream catalog JSON |
| `goe:advisory:{country_code}` | 1800s | Latest advisory per country |

---

## SECTION 21 — SIGNAL DOMAIN MAPPING

Use these domain values consistently (they feed into the existing `IntelligenceItem.domain` column and the frontend's filter UI):

```python
DOMAIN_MAP = {
    "geopolitics": ["wire", "gov", "mainstream", "intel", "mena", "asia", "africa", "india", "state_media"],
    "defense":     ["defense", "military"],
    "economics":   ["markets", "energy", "finance"],
    "technology":  ["tech", "cyber"],
    "health":      ["health", "humanitarian"],
    "climate":     ["climate", "disaster"],
}
```

---

## SECTION 22 — DEPENDENCY ADDITIONS

Add these to your `requirements.txt` / `pyproject.toml`:

```txt
feedparser>=6.0.11          # RSS/Atom parsing
h3>=3.7.7                   # H3 hexagonal grid for GPS jamming
httpx[http2]>=0.27.0        # HTTP/2 support for better TLS fingerprinting
aiofiles>=23.0.0            # Async file I/O for city translation dict
geopy>=2.4.1                # Haversine distance computation for disaster dedup
```

---

## SUMMARY — ALL CONNECTORS TO BUILD

| # | File | SOURCE_NAME | Poll Interval | New |
|---|---|---|---|---|
| 1 | `mass_rss.py` | `mass_rss_aggregator` | 15 min | ✅ |
| 2 | `gov_advisories.py` | `gov_advisories` | 30 min | ✅ |
| 3 | `cyber_ioc.py` | `cyber_ioc_feeds` | 10 min | ✅ |
| 4 | `natural_disasters.py` | `natural_disasters` | 5 min | ✅ |
| 5 | `nasa_firms.py` | `nasa_firms` | 30 min | upgrade |
| 6 | `climate_anomalies.py` | `climate_anomalies` | 1 hour | ✅ |
| 7 | `aviation_delays.py` | `aviation_delays` | 5 min | ✅ |
| 8 | `internet_outages.py` | `cloudflare_radar` | 5 min | ✅ |
| 9 | `gps_jamming.py` | `gps_jamming` | 1 hour | ✅ |
| 10 | `yahoo_finance.py` | `yahoo_finance` | 5 min | upgrade |
| 11 | `coingecko.py` | `coingecko_markets` | 5 min | upgrade |
| 12 | `fred_economic.py` | `fred_economic` | 1 hour | ✅ |
| 13 | `eia_energy.py` | `eia_energy` | 1 hour | ✅ |
| 14 | `polymarket.py` | `polymarket_predictions` | 5 min | ✅ |
| 15 | `bis_data.py` | `bis_central_banks` | 24 hours | ✅ |
| 16 | `wto_trade.py` | `wto_trade` | 1 hour | ✅ |
| 17 | `humanitarian.py` | `humanitarian_data` | 1 hour | ✅ |
| 18 | `oref_alerts.py` | `oref_rocket_alerts` | 5 min | ✅ |
| 19 | `iran_liveuamap.py` | `iran_liveuamap` | 5 min | ✅ |
| 20 | `health_feeds.py` | `global_health_feeds` | 30 min | ✅ |
| 21 | `live_streams.py` | `live_stream_catalog` | 1 hour | ✅ |
| 22 | `gdelt.py` | `gdelt_events` | 10 min | upgrade |

Total: **22 connectors** covering all worldmonitor.app feed categories at matching refresh intervals.

---

*End of prompt. Implement each section in the order listed. Start with Section 17 (scheduler) last, after all connectors are implemented and tested individually.*
