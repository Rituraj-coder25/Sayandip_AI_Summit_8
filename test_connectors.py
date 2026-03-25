"""
Standalone connector test harness (v2).
Exercises fetch() + parse() for every connector against live APIs.
No Docker/Redis/Postgres required (uses a fake Redis shim).
"""
import asyncio
import sys
import os
import traceback
import time
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "apps", "api"))
sys.path.insert(0, os.path.join(ROOT, "apps"))

# Fake Redis shim
class FakeRedis:
    def __init__(self):
        self._store = {}
    async def get(self, key):
        return self._store.get(key)
    async def set(self, key, value, *a, **kw):
        self._store[key] = value
    async def setex(self, key, ttl, value):
        self._store[key] = value
    async def hset(self, key, mapping=None, **kw):
        if mapping:
            self._store.setdefault(key, {}).update(mapping)
    async def hget(self, key, field):
        return self._store.get(key, {}).get(field)
    async def delete(self, key):
        self._store.pop(key, None)
    async def incr(self, key):
        self._store[key] = int(self._store.get(key, 0)) + 1
        return self._store[key]
    async def expire(self, key, ttl):
        pass
    async def publish(self, channel, msg):
        pass

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

import httpx
from api.config import settings
from api.ingestion.base_connector import BaseConnector

CONNECTOR_CLASSES = []

def _import_connector(module_path, class_name):
    try:
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        CONNECTOR_CLASSES.append((class_name, cls))
    except Exception as e:
        print(f"  [IMPORT ERROR] {class_name}: {e}")

# All connectors
_import_connector("api.ingestion.connectors.acled", "ACLEDConnector")
_import_connector("api.ingestion.connectors.coingecko", "CoinGeckoConnector")
_import_connector("api.ingestion.connectors.gdelt", "GDELTConnector")
_import_connector("api.ingestion.connectors.iaea", "IAEAConnector")
_import_connector("api.ingestion.connectors.india_gov", "IndiaGovConnector")
_import_connector("api.ingestion.connectors.nasa_firms", "NASAFirmsConnector")
_import_connector("api.ingestion.connectors.noaa", "NOAAConnector")
_import_connector("api.ingestion.connectors.opensky", "OpenSkyConnector")
_import_connector("api.ingestion.connectors.reliefweb", "ReliefWebConnector")
_import_connector("api.ingestion.connectors.usgs", "USGSConnector")
_import_connector("api.ingestion.connectors.who", "WHOConnector")
_import_connector("api.ingestion.connectors.worldbank", "WorldBankConnector")
_import_connector("api.ingestion.connectors.yahoo_finance", "YahooFinanceConnector")
_import_connector("api.ingestion.connectors.mass_rss", "MassRSSAggregatorConnector")
_import_connector("api.ingestion.connectors.gov_advisories", "GovAdvisoryConnector")
_import_connector("api.ingestion.connectors.cyber_ioc", "CyberIOCConnector")
_import_connector("api.ingestion.connectors.natural_disasters", "NaturalDisasterConnector")
_import_connector("api.ingestion.connectors.climate_anomalies", "ClimateAnomalyConnector")
_import_connector("api.ingestion.connectors.aviation_delays", "AviationDelaysConnector")
_import_connector("api.ingestion.connectors.internet_outages", "InternetOutagesConnector")
_import_connector("api.ingestion.connectors.gps_jamming", "GPSJammingConnector")
_import_connector("api.ingestion.connectors.fred_economic", "FREDEconomicConnector")
_import_connector("api.ingestion.connectors.eia_energy", "EIAEnergyConnector")
_import_connector("api.ingestion.connectors.polymarket", "PolymarketConnector")
_import_connector("api.ingestion.connectors.bis_data", "BISDataConnector")
_import_connector("api.ingestion.connectors.wto_trade", "WTOTradeConnector")
_import_connector("api.ingestion.connectors.humanitarian", "HumanitarianConnector")
_import_connector("api.ingestion.connectors.oref_alerts", "OREFAlertsConnector")
_import_connector("api.ingestion.connectors.iran_liveuamap", "IranLiveUAMapConnector")
_import_connector("api.ingestion.connectors.health_feeds", "GlobalHealthFeedsConnector")
_import_connector("api.ingestion.connectors.live_streams", "LiveStreamCatalogConnector")
_import_connector("api.ingestion.connectors.ucdp", "UCDPConnector")
_import_connector("api.ingestion.connectors.nga_navwarnings", "NGANavWarningsConnector")


async def test_connector(name, cls, redis, http):
    connector = cls(redis, http)
    
    # Determine the right fetch method
    has_fetch_raw = hasattr(cls, 'fetch_raw') and cls.fetch_raw is not BaseConnector.fetch_raw
    
    # Fetch
    t0 = time.perf_counter()
    try:
        if has_fetch_raw:
            payload = await connector.fetch_raw()
        else:
            payload = await connector.fetch()
        fetch_ms = round((time.perf_counter() - t0) * 1000)
        
        if payload is None:
            desc = "None"
        elif isinstance(payload, dict):
            desc = f"dict keys={list(payload.keys())[:8]}"
        elif isinstance(payload, list):
            desc = f"list len={len(payload)}"
        elif isinstance(payload, str):
            desc = f"string len={len(payload)}"
        else:
            desc = f"type={type(payload).__name__}"
        print(f"  [FETCH] {desc} ({fetch_ms}ms)")
    except Exception as e:
        fetch_ms = round((time.perf_counter() - t0) * 1000)
        print(f"  [FETCH ERROR] {type(e).__name__}: {e} ({fetch_ms}ms)")
        return name, "FETCH_ERROR", str(e)[:80]
    
    # Parse
    t1 = time.perf_counter()
    try:
        signals = await connector.parse(payload) if payload is not None else []
        parse_ms = round((time.perf_counter() - t1) * 1000)
        
        if signals:
            first_title = str(signals[0].get('title', '?'))[:60]
            print(f"  [PARSE] {len(signals)} signals ({parse_ms}ms)")
            print(f"    -> First: {first_title}")
        else:
            print(f"  [PARSE] 0 signals ({parse_ms}ms)")
        
        return name, "OK", f"{len(signals)} signals"
    except Exception as e:
        parse_ms = round((time.perf_counter() - t1) * 1000)
        print(f"  [PARSE ERROR] {type(e).__name__}: {e} ({parse_ms}ms)")
        return name, "PARSE_ERROR", str(e)[:80]


async def main():
    print(f"GOE Connector Integration Test - {len(CONNECTOR_CLASSES)} connectors")
    print("=" * 70)
    
    redis = FakeRedis()
    http = httpx.AsyncClient(
        headers={"User-Agent": "GOE-Intelligence/4.0"},
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    )
    
    results = []
    for name, cls in CONNECTOR_CLASSES:
        src = cls.SOURCE_NAME if hasattr(cls, 'SOURCE_NAME') else '?'
        print(f"\n--- {name} ({src}) ---")
        try:
            result = await test_connector(name, cls, redis, http)
            results.append(result)
        except Exception as e:
            print(f"  [FATAL] {e}")
            results.append((name, "FATAL", str(e)[:80]))
    
    await http.aclose()
    
    # Summary
    print("\n\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    ok = err = 0
    for name, status, detail in results:
        icon = "OK" if status == "OK" else "ERR"
        if status == "OK":
            ok += 1
        else:
            err += 1
        print(f"  [{icon:3s}] {name:40s} {detail}")
    
    print(f"\nTotal: {ok} OK, {err} errors out of {len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
