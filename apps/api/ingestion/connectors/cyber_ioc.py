"""Section 3 – Cybersecurity IOC Feeds (6 feeds, 10-min poll)."""
from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import UTC, datetime, timedelta

from ..base_connector import BaseConnector
from ...config import settings

MAX_IOC_DISPLAY = 500
ROLLING_WINDOW_DAYS = 14
GEO_ENRICHMENT_CAP = 250
GEO_CONCURRENCY = 16

IOC_TYPE_MAP = {
    "feodo":       "c2_server",
    "urlhaus":     "malware_host",
    "c2intel":     "c2_server",
    "alienvault":  "mixed",
    "abuseipdb":   "malicious_ip",
    "ransomware":  "ransomware",
}


class CyberIOCConnector(BaseConnector):
    SOURCE_NAME = "cyber_ioc_feeds"
    POLL_INTERVAL_SECONDS = 600
    CACHE_TTL_SECONDS = 600

    async def fetch(self):
        results: dict[str, object] = {}
        # Feodo
        try:
            results["feodo"] = await self.fetch_json(
                "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
            )
        except Exception:
            results["feodo"] = None
        # URLhaus
        try:
            results["urlhaus"] = await self.fetch_json(
                "https://urlhaus-api.abuse.ch/v1/urls/recent/"
            )
        except Exception:
            results["urlhaus"] = None
        # C2IntelFeeds CSV
        try:
            text = await self.fetch_text(
                "https://raw.githubusercontent.com/drb-ra/C2IntelFeeds/master/feeds/IPC2s.csv"
            )
            results["c2intel"] = text
        except Exception:
            results["c2intel"] = None
        # AlienVault OTX
        if settings.ALIENVAULT_OTX_KEY:
            try:
                results["alienvault"] = await self.fetch_json(
                    "https://otx.alienvault.com/api/v1/pulses/subscribed",
                    headers={"X-OTX-API-KEY": settings.ALIENVAULT_OTX_KEY},
                )
            except Exception:
                results["alienvault"] = None
        # AbuseIPDB
        if settings.ABUSEIPDB_API_KEY:
            try:
                results["abuseipdb"] = await self.fetch_json(
                    "https://api.abuseipdb.com/api/v2/blacklist",
                    headers={
                        "Key": settings.ABUSEIPDB_API_KEY,
                        "Accept": "application/json",
                    },
                    params={"confidenceMinimum": "90", "limit": "200"},
                )
            except Exception:
                results["abuseipdb"] = None
        # Ransomware.live
        try:
            results["ransomware"] = await self.fetch_json(
                "https://api.ransomware.live/recentvictims"
            )
        except Exception:
            results["ransomware"] = None
        return results

    # ── Geo-enrichment ──
    async def _geo_lookup(self, ip: str) -> dict | None:
        cached = await self.redis.get(f"goe:geo:{ip}")
        if cached:
            return json.loads(cached)
            
        ipinfo_url = f"https://ipinfo.io/{ip}/json"
        if settings.IPINFO_TOKEN:
            ipinfo_url = f"https://ipinfo.io/{ip}/json?token={settings.IPINFO_TOKEN}"
            
        for url in [
            ipinfo_url,
            f"https://freeipapi.com/api/json/{ip}",
        ]:
            try:
                data = await self.fetch_json(url)
                result = {
                    "country": data.get("country") or data.get("countryCode") or "",
                    "latitude": data.get("latitude") or _parse_loc(data.get("loc"), 0),
                    "longitude": data.get("longitude") or _parse_loc(data.get("loc"), 1),
                }
                await self.redis.setex(f"goe:geo:{ip}", 86400, json.dumps(result))
                return result
            except Exception:
                continue
        return None

    async def _enrich_batch(self, ips: list[str]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for i in range(0, len(ips), GEO_CONCURRENCY):
            batch = ips[i : i + GEO_CONCURRENCY]
            lookups = await asyncio.gather(
                *[self._geo_lookup(ip) for ip in batch],
                return_exceptions=True,
            )
            for ip, geo in zip(batch, lookups):
                if isinstance(geo, dict):
                    results[ip] = geo
        return results

    async def parse(self, payload) -> list[dict]:
        iocs: list[dict] = []
        cutoff = datetime.now(UTC) - timedelta(days=ROLLING_WINDOW_DAYS)

        # Feodo
        if payload.get("feodo"):
            for item in (payload["feodo"] if isinstance(payload["feodo"], list) else []):
                iocs.append({
                    "ioc_value": item.get("ip_address", ""),
                    "ioc_source": "feodo_tracker",
                    "ioc_type": "c2_server",
                    "port": item.get("port"),
                    "malware": item.get("malware"),
                })

        # URLhaus
        if payload.get("urlhaus"):
            urls = payload["urlhaus"].get("urls", []) if isinstance(payload["urlhaus"], dict) else []
            for item in urls[:200]:
                iocs.append({
                    "ioc_value": item.get("url", ""),
                    "ioc_source": "urlhaus",
                    "ioc_type": "malware_host",
                    "threat": item.get("threat"),
                })

        # C2IntelFeeds CSV
        if payload.get("c2intel"):
            reader = csv.reader(io.StringIO(payload["c2intel"]))
            for row in reader:
                if row and not row[0].startswith("#"):
                    iocs.append({
                        "ioc_value": row[0].strip(),
                        "ioc_source": "c2intel",
                        "ioc_type": "c2_server",
                    })

        # AbuseIPDB
        if payload.get("abuseipdb"):
            data = payload["abuseipdb"].get("data", []) if isinstance(payload["abuseipdb"], dict) else []
            for item in data[:200]:
                iocs.append({
                    "ioc_value": item.get("ipAddress", ""),
                    "ioc_source": "abuseipdb",
                    "ioc_type": "malicious_ip",
                    "abuse_confidence": item.get("abuseConfidenceScore"),
                })

        # Ransomware.live
        if payload.get("ransomware"):
            for item in (payload["ransomware"] if isinstance(payload["ransomware"], list) else [])[:100]:
                iocs.append({
                    "ioc_value": item.get("website") or item.get("post_title", ""),
                    "ioc_source": "ransomware_live",
                    "ioc_type": "ransomware",
                    "group": item.get("group_name"),
                })

        # Geo-enrich IP-based IOCs
        ip_iocs = [i for i in iocs if _is_ip(i["ioc_value"])][:GEO_ENRICHMENT_CAP]
        ip_list = [i["ioc_value"] for i in ip_iocs]
        geo_map = await self._enrich_batch(ip_list) if ip_list else {}

        # Build signals
        signals = []
        for ioc in iocs[:MAX_IOC_DISPLAY]:
            geo = geo_map.get(ioc["ioc_value"], {})
            signals.append(
                self.std_signal(
                    id=f"ioc-{ioc['ioc_source']}-{ioc['ioc_value'][:64]}",
                    title=f"IOC: {ioc['ioc_type']} — {ioc['ioc_value'][:60]}",
                    summary=f"{ioc['ioc_type']} indicator from {ioc['ioc_source']}",
                    domain="technology",
                    severity=60,
                    india_score=5,
                    url="",
                    raw={**ioc, **geo},
                    tags=["cyber", "ioc", ioc["ioc_type"]],
                    latitude=geo.get("latitude"),
                    longitude=geo.get("longitude"),
                )
            )
        return signals


def _parse_loc(loc: str | None, idx: int) -> float | None:
    if not loc:
        return None
    try:
        parts = loc.split(",")
        return float(parts[idx])
    except (IndexError, ValueError):
        return None


def _is_ip(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
