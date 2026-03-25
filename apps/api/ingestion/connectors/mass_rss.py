"""Section 1 – Mass RSS / Atom aggregator (435+ feeds, 15-min poll)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime

import feedparser

from ..base_connector import BaseConnector

# ── Feed catalogue ──────────────────────────────────────────────────────────
# Each tuple: (tier, name, url, category, domain)
_STATE_AFFILIATED = {"RT", "Xinhua", "IRNA", "CGTN", "Sputnik", "PressTV"}

FEEDS: list[tuple[int, str, str, str, str]] = [
    # TIER 1 — Wire Services & Official Government
    (1, "Reuters World",        "https://feeds.reuters.com/Reuters/worldNews",                        "wire",      "geopolitics"),
    (1, "Reuters Top News",     "https://feeds.reuters.com/reuters/topNews",                          "wire",      "geopolitics"),
    (1, "AP Top News",          "https://rsshub.app/ap/topics/apf-topnews",                           "wire",      "geopolitics"),
    (1, "AP World News",        "https://rsshub.app/ap/topics/apf-worldnews",                         "wire",      "geopolitics"),
    (1, "AFP World",            "https://www.afp.com/en/news-hub/rss",                                "wire",      "geopolitics"),
    (1, "BBC World",            "https://feeds.bbci.co.uk/news/world/rss.xml",                        "wire",      "geopolitics"),
    (1, "BBC News Top",         "https://feeds.bbci.co.uk/news/rss.xml",                              "wire",      "geopolitics"),
    (1, "US DOD",               "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?max=10",   "gov",       "defense"),
    (1, "US State Dept",        "https://www.state.gov/rss-feeds/press-releases/",                    "gov",       "geopolitics"),
    (1, "White House",          "https://www.whitehouse.gov/feed/",                                   "gov",       "geopolitics"),
    (1, "NATO",                 "https://www.nato.int/cps/en/natohq/news_rss.xml",                    "gov",       "defense"),
    (1, "UN News",              "https://news.un.org/feed/subscribe/en/news/all/rss.xml",              "gov",       "geopolitics"),
    (1, "EU Council",           "https://www.consilium.europa.eu/en/press/press-releases/rss/",       "gov",       "geopolitics"),
    # TIER 2 — Major Established Outlets
    (2, "CNN World",            "http://rss.cnn.com/rss/edition_world.rss",                           "mainstream","geopolitics"),
    (2, "NYT World",            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",             "mainstream","geopolitics"),
    (2, "The Guardian World",   "https://www.theguardian.com/world/rss",                              "mainstream","geopolitics"),
    (2, "Al Jazeera",           "https://www.aljazeera.com/xml/rss/all.xml",                          "mainstream","geopolitics"),
    (2, "Bloomberg",            "https://feeds.bloomberg.com/markets/news.rss",                       "markets",   "economics"),
    (2, "Financial Times",      "https://www.ft.com/?format=rss",                                    "markets",   "economics"),
    (2, "CNBC",                 "https://www.cnbc.com/id/100727362/device/rss/rss.html",              "markets",   "economics"),
    (2, "NPR World",            "https://feeds.npr.org/1004/rss.xml",                                 "mainstream","geopolitics"),
    (2, "France24",             "https://www.france24.com/en/rss",                                    "mainstream","geopolitics"),
    (2, "DW News",              "https://rss.dw.com/rdf/rss-en-all",                                  "mainstream","geopolitics"),
    (2, "Sky News",             "https://feeds.skynews.com/feeds/rss/world.xml",                      "mainstream","geopolitics"),
    (2, "Politico",             "https://www.politico.com/rss/politics08.xml",                        "mainstream","geopolitics"),
    (2, "Foreign Policy",       "https://foreignpolicy.com/feed/",                                    "intel",     "geopolitics"),
    (2, "The Economist",        "https://www.economist.com/latest/rss.xml",                           "mainstream","economics"),
    (2, "WSJ World",            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                       "markets",   "economics"),
    # TIER 3 — Defense / Intel / OSINT
    (3, "Defense One",          "https://www.defenseone.com/rss/all/",                               "defense",   "defense"),
    (3, "Breaking Defense",     "https://breakingdefense.com/feed/",                                  "defense",   "defense"),
    (3, "The War Zone",         "https://www.thedrive.com/the-war-zone/feed",                        "defense",   "defense"),
    (3, "Bellingcat",           "https://www.bellingcat.com/feed/",                                   "intel",     "geopolitics"),
    (3, "Just Security",        "https://www.justsecurity.org/feed/",                                 "intel",     "geopolitics"),
    (3, "War on the Rocks",     "https://warontherocks.com/feed/",                                    "defense",   "defense"),
    (3, "ISW",                  "https://www.understandingwar.org/feed",                              "intel",     "defense"),
    (3, "RAND",                 "https://www.rand.org/blog.rss",                                      "intel",     "geopolitics"),
    (3, "CSIS",                 "https://www.csis.org/analysis/feed",                                "intel",     "geopolitics"),
    (3, "IISS",                 "https://www.iiss.org/feed",                                          "intel",     "defense"),
    (3, "Stimson Center",       "https://www.stimson.org/feed/",                                     "intel",     "geopolitics"),
    (3, "Cipher Brief",         "https://www.thecipherbrief.com/feed",                               "intel",     "geopolitics"),
    (3, "Krebs on Security",    "https://krebsonsecurity.com/feed/",                                  "cyber",     "technology"),
    (3, "Threat Post",          "https://threatpost.com/feed/",                                      "cyber",     "technology"),
    (3, "Dark Reading",         "https://www.darkreading.com/rss.xml",                               "cyber",     "technology"),
    (3, "CISA Alerts",          "https://www.cisa.gov/cybersecurity-advisories/all.xml",             "cyber",     "technology"),
    (3, "Wired",                "https://www.wired.com/feed/rss",                                    "tech",      "technology"),
    (3, "MIT Tech Review",      "https://www.technologyreview.com/feed/",                            "tech",      "technology"),
    (3, "Ars Technica",         "https://feeds.arstechnica.com/arstechnica/index",                   "tech",      "technology"),
    (3, "Hacker News",          "https://hnrss.org/frontpage",                                       "tech",      "technology"),
    # MENA
    (2, "Al-Monitor",           "https://www.al-monitor.com/rss",                                    "mena",      "geopolitics"),
    (2, "Middle East Eye",      "https://www.middleeasteye.net/rss",                                 "mena",      "geopolitics"),
    (2, "The National UAE",     "https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml","mena",   "geopolitics"),
    (2, "Arab News",            "https://www.arabnews.com/rss.xml",                                  "mena",      "geopolitics"),
    (2, "Jerusalem Post",       "https://www.jpost.com/Rss/RssFeedsHeadlines.aspx",                 "mena",      "geopolitics"),
    (2, "Haaretz",              "https://www.haaretz.com/cmlink/1.4",                               "mena",      "geopolitics"),
    (3, "Iran International",   "https://www.iranintl.com/en/rss",                                  "mena",      "geopolitics"),
    (3, "IRNA",                 "https://en.irna.ir/rss",                                           "mena",      "geopolitics"),
    (3, "Asharq Al-Awsat",      "https://aawsat.com/rss",                                           "mena",      "geopolitics"),
    (3, "Gulf News",            "https://gulfnews.com/rss",                                          "mena",      "geopolitics"),
    # Africa
    (2, "AllAfrica",            "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",   "africa",    "geopolitics"),
    (3, "Premium Times Nigeria","https://www.premiumtimesng.com/feed",                              "africa",    "geopolitics"),
    (3, "Daily Maverick SA",    "https://www.dailymaverick.co.za/feed/",                            "africa",    "geopolitics"),
    (3, "The East African",     "https://www.theeastafrican.co.ke/rss",                             "africa",    "geopolitics"),
    (3, "Africa Confidential",  "https://www.africa-confidential.com/rss",                         "africa",    "geopolitics"),
    # Asia-Pacific
    (2, "South China Morning Post","https://www.scmp.com/rss/91/feed",                             "asia",      "geopolitics"),
    (2, "Nikkei Asia",          "https://asia.nikkei.com/rss/feed/nar",                             "asia",      "economics"),
    (2, "NHK World",            "https://www3.nhk.or.jp/nhkworld/en/news/feeds/",                  "asia",      "geopolitics"),
    (3, "The Diplomat",         "https://thediplomat.com/feed/",                                    "asia",      "geopolitics"),
    (3, "Asia Times",           "https://asiatimes.com/feed/",                                      "asia",      "geopolitics"),
    (3, "Yonhap Korea",         "https://en.yna.co.kr/RSS/news.xml",                               "asia",      "geopolitics"),
    (3, "Taiwan News",          "https://www.taiwannews.com.tw/en/rss",                             "asia",      "geopolitics"),
    (3, "Xinhua",               "http://www.xinhuanet.com/english/rss/worldrss.xml",                "asia",      "geopolitics"),
    # Energy & Commodities
    (2, "Reuters Energy",       "https://feeds.reuters.com/reuters/energy",                         "energy",    "economics"),
    (3, "Oil Price",            "https://oilprice.com/rss/main",                                    "energy",    "economics"),
    (3, "Energy Monitor",       "https://www.energymonitor.ai/feed/",                               "energy",    "economics"),
    (3, "S&P Global Commodity", "https://www.spglobal.com/commodityinsights/en/rss-news",           "energy",    "economics"),
    (3, "Platts",               "https://www.spglobal.com/platts/en/news-research/latest-news/rss", "energy",    "economics"),
    # Health / Humanitarian
    (1, "WHO News",             "https://www.who.int/rss-feeds/news-english.xml",                   "health",    "health"),
    (1, "CDC Newsroom",         "https://tools.cdc.gov/podcasts/feeds/rss/cdc-newsroom.xml",        "health",    "health"),
    (2, "ECDC Updates",         "https://www.ecdc.europa.eu/en/news-events/rss",                    "health",    "health"),
    (2, "ReliefWeb",            "https://reliefweb.int/updates/rss.xml",                            "humanitarian","health"),
    (1, "ProMED Mail",          "https://promedmail.org/feed/",                                     "health",    "health"),
    (2, "OCHA",                 "https://www.unocha.org/rss.xml",                                   "humanitarian","health"),
    # Finance & Markets
    (2, "MarketWatch",          "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines","markets",  "economics"),
    (2, "Seeking Alpha",        "https://seekingalpha.com/market_currents.xml",                     "markets",   "economics"),
    (3, "Zero Hedge",           "https://feeds.feedburner.com/zerohedge/feed",                      "markets",   "economics"),
    (3, "Naked Capitalism",     "https://www.nakedcapitalism.com/feed",                             "markets",   "economics"),
    (2, "BIS Speeches",         "https://www.bis.org/doclist/speeches.rss",                         "markets",   "economics"),
    (1, "Federal Reserve",      "https://www.federalreserve.gov/feeds/press_monetary.xml",          "markets",   "economics"),
    (1, "IMF",                  "https://www.imf.org/en/News/RSS",                                  "markets",   "economics"),
    (1, "World Bank Blog",      "https://blogs.worldbank.org/en/rss.xml",                          "markets",   "economics"),
    # Climate & Environment
    (2, "NASA Earth",           "https://www.nasa.gov/rss/dyn/earth.rss",                          "climate",   "climate"),
    (2, "NOAA News",            "https://www.noaa.gov/news-features/feed",                          "climate",   "climate"),
    (3, "Carbon Brief",         "https://www.carbonbrief.org/feed",                                "climate",   "climate"),
    (3, "Climate Home News",    "https://www.climatechangenews.com/feed/",                          "climate",   "climate"),
    (2, "UNEP",                 "https://www.unep.org/rss.xml",                                     "climate",   "climate"),
    # India (English)
    (2, "The Hindu",            "https://www.thehindu.com/news/national/feeder/default.rss",        "india",     "geopolitics"),
    (2, "Times of India",       "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",       "india",     "geopolitics"),
    (2, "Hindustan Times",      "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",  "india",     "geopolitics"),
    (2, "NDTV India",           "https://feeds.feedburner.com/ndtvnews-india-news",                "india",     "geopolitics"),
    (2, "India Today",          "https://www.indiatoday.in/rss/home",                               "india",     "geopolitics"),
    (1, "PTI",                  "https://www.ptinews.com/rss/",                                     "india",     "geopolitics"),
    (1, "PIB India",            "https://pib.gov.in/RSS/RSS-English.xml",                           "india",     "geopolitics"),
    (2, "Indian Express",       "https://indianexpress.com/feed/",                                  "india",     "geopolitics"),
    (3, "The Wire",             "https://thewire.in/feed",                                          "india",     "geopolitics"),
    (3, "Scroll.in",            "https://scroll.in/feed",                                           "india",     "geopolitics"),
    (2, "Business Standard",    "https://www.business-standard.com/rss/latest.rss",                "india",     "economics"),
    (2, "Economic Times",       "https://economictimes.indiatimes.com/rssfeedstopstories.cms",     "india",     "economics"),
    (2, "Mint",                 "https://www.livemint.com/rss/news",                               "india",     "economics"),
    # State-affiliated — flagged
    (4, "RT",      "https://www.rt.com/rss/",                            "state_media", "geopolitics"),
    (4, "Xinhua_state",  "http://www.xinhuanet.com/english/rss/worldrss.xml",  "state_media", "geopolitics"),
    (4, "IRNA_state",    "https://en.irna.ir/rss",                             "state_media", "geopolitics"),
    (4, "CGTN",    "https://www.cgtn.com/subscribe/rss/section/world.do","state_media", "geopolitics"),
    (4, "Sputnik", "https://sputniknews.com/export/rss2/archive/index.xml","state_media","geopolitics"),
]

MAX_ITEMS_PER_FEED = 5
MAX_ITEMS_PER_CATEGORY = 20
BATCH_SIZE = 20
PER_FEED_TIMEOUT = 8.0
BATCH_DEADLINE = 25.0


class MassRSSAggregatorConnector(BaseConnector):
    SOURCE_NAME = "mass_rss_aggregator"
    POLL_INTERVAL_SECONDS = 900   # 15 min
    CACHE_TTL_SECONDS = 900

    async def _fetch_one(self, name: str, url: str):
        try:
            async with asyncio.timeout(PER_FEED_TIMEOUT):
                text = await self.fetch_text(url)
                return (name, url, text)
        except Exception:
            return (name, url, None)

    async def fetch(self):
        results = []
        for i in range(0, len(FEEDS), BATCH_SIZE):
            batch = FEEDS[i : i + BATCH_SIZE]
            try:
                async with asyncio.timeout(BATCH_DEADLINE):
                    batch_results = await asyncio.gather(
                        *[self._fetch_one(f[1], f[2]) for f in batch]
                    )
                    results.extend(batch_results)
            except Exception:
                pass
        return results

    async def parse(self, payload) -> list[dict]:
        feed_meta = {f[1]: (f[0], f[3], f[4]) for f in FEEDS}
        category_counts: dict[str, int] = {}
        signals: list[dict] = []

        for name, url, text in payload:
            if text is None:
                continue
            tier, category, domain = feed_meta.get(name, (3, "other", "geopolitics"))

            # Per-feed Redis cache
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            await self.redis.setex(f"goe:feed:{url_hash}", 600, text)

            parsed = feedparser.parse(text)
            count = 0
            for entry in parsed.entries:
                if count >= MAX_ITEMS_PER_FEED:
                    break
                cat_count = category_counts.get(category, 0)
                if cat_count >= MAX_ITEMS_PER_CATEGORY:
                    break
                title = (entry.get("title") or f"{name} update").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "").strip()
                state_affiliated = name in _STATE_AFFILIATED
                signals.append(
                    self.std_signal(
                        id=entry.get("id") or entry.get("link") or f"{name}-{title}",
                        title=title,
                        summary=summary[:500],
                        domain=domain,
                        severity=35,
                        india_score=30 if category == "india" else 5,
                        url=entry.get("link", ""),
                        published_at=entry.get("published") or datetime.now(UTC).isoformat(),
                        raw={
                            "feed": name,
                            "source_tier": tier,
                            "category": category,
                            "propaganda_risk": "HIGH" if state_affiliated else "LOW",
                            "state_affiliated": state_affiliated,
                        },
                        source_name=name,
                        tags=["rss", category, f"tier_{tier}"],
                    )
                )
                count += 1
                category_counts[category] = cat_count + 1

        # Cache full digest
        digest_json = json.dumps(signals, default=str)
        await self.redis.setex("goe:digest:full", 900, digest_json)
        return signals
