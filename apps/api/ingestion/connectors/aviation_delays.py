"""Section 7 – Aviation Delays / NOTAMs (3 sources, 5-min poll)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import time

from ..base_connector import BaseConnector
from ...config import settings

_LAST_ICAO_CALL = 0.0

FAA_AIRPORTS = ["ATL", "LAX", "ORD", "DFW", "DEN", "SFO", "SEA", "LAS", "MCO", "EWR", "JFK", "LGA", "BOS", "MIA"]

INTL_AIRPORTS = [
    "EGLL", "EDDF", "LFPG", "LIRF", "LEMD", "EHAM", "LSZH", "OMDB", "OTHH", "OBBI",
    "OJAM", "LLBG", "LTFM", "VVTS", "WSSS", "VTBS", "VIDP", "VOBL", "RJTT", "RKSI",
    "ZSSS", "ZBAA", "VHHH", "YSSY", "YMML", "FAOR", "HAAB", "DNMM", "DIAP", "HECA",
]

MENA_AIRPORTS = [
    "OMDB", "OBBI", "OTHH", "OEDF", "OEJN", "LLBG", "OJAM", "OSDI", "LTFM", "LTAC",
    "HECA", "HESH", "VIDF", "VIDP", "OPKC", "OPLA", "OJAI", "OKBK", "OMAA", "OMSJ",
    "ORMM", "ORBI", "OBIC", "OIIE", "OIKB", "OIKK", "OISS", "OIZH", "OISL", "OIFS",
    "OIFM", "OIAW", "OICC", "OIGG", "OITT", "OITR", "OIAH", "OIZB", "OIZI", "OIKE",
    "OIKR", "OIBS", "OIBP", "OIBL", "OIBK", "OIBH",
]

CLOSURE_KEYWORDS = ["AD CLSD", "AIRPORT CLOSED", "AIRSPACE CLOSED", "CLSD TO", "CLOSED"]


def _delay_severity(minutes: float) -> tuple[str, int]:
    if minutes >= 60:
        return "severe", 80
    if minutes >= 45:
        return "major", 65
    if minutes >= 30:
        return "moderate", 50
    if minutes >= 15:
        return "minor", 35
    return "normal", 0


class AviationDelaysConnector(BaseConnector):
    SOURCE_NAME = "aviation_delays"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 1800

    async def fetch(self):
        results: dict[str, object] = {}
        # FAA ASWS
        if settings.FAA_ASWS_ENABLED:
            try:
                results["faa"] = await self.fetch_text(
                    "https://nasstatus.faa.gov/api/airport-status-information"
                )
            except Exception:
                results["faa"] = None
        # AviationStack (top-3 international airports to limit API calls)
        if settings.AVIATIONSTACK_API_KEY:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            calls_today = int(await self.redis.get(f"aviationstack_calls:{today}") or 0)
            
            if calls_today >= 3:
                results["aviationstack"] = []
            else:
                avstack_data = []
                for icao in INTL_AIRPORTS[:3]:
                    try:
                        data = await self.fetch_json(
                            "http://api.aviationstack.com/v1/flights",
                            params={
                                "access_key": settings.AVIATIONSTACK_API_KEY,
                                "dep_icao": icao,
                                "limit": "100",
                            },
                        )
                        avstack_data.append({"icao": icao, "data": data})
                        await self.redis.incr(f"aviationstack_calls:{today}")
                    except Exception:
                        pass
                await self.redis.expire(f"aviationstack_calls:{today}", 172800)
                results["aviationstack"] = avstack_data
        # ICAO NOTAM
        global _LAST_ICAO_CALL
        if settings.ICAO_API_KEY:
            current_time = time.time()
            if current_time - _LAST_ICAO_CALL >= 6048:  # 1.68 hours
                icao_codes = ",".join(MENA_AIRPORTS)
                try:
                    results["notam"] = await self.fetch_json(
                        f"https://applications.icao.int/dataservices/api/notams",
                        params={"api_key": settings.ICAO_API_KEY, "icaos": icao_codes, "format": "json"},
                    )
                    _LAST_ICAO_CALL = current_time
                except Exception:
                    results["notam"] = None
        return results

    async def parse(self, payload) -> list[dict]:
        signals: list[dict] = []

        # FAA
        if payload.get("faa"):
            try:
                root = ET.fromstring(payload["faa"])
                for delay in root.iter():
                    if "delay" in delay.tag.lower() or "status" in delay.tag.lower():
                        airport = delay.findtext("ARPT", "") or delay.findtext("airport", "")
                        reason = delay.findtext("Reason", "") or delay.findtext("reason", "")
                        avg_text = delay.findtext("avgDelay", "") or delay.findtext("Avg", "0")
                        try:
                            minutes = float("".join(c for c in avg_text if c.isdigit() or c == ".") or "0")
                        except ValueError:
                            minutes = 0
                        label, sev = _delay_severity(minutes)
                        if sev > 0:
                            signals.append(
                                self.std_signal(
                                    id=f"faa-{airport}-{datetime.now(UTC).strftime('%Y%m%dT%H')}",
                                    title=f"FAA Delay: {airport} — {label}",
                                    summary=f"{reason}. Average delay {minutes:.0f} min",
                                    domain="economics",
                                    severity=sev,
                                    india_score=5,
                                    raw={"source": "faa", "airport": airport, "delay_min": minutes},
                                    tags=["aviation", "delay", "faa", airport.lower()],
                                )
                            )
            except ET.ParseError:
                pass

        # AviationStack
        for entry in payload.get("aviationstack", []):
            icao = entry.get("icao", "")
            flights = (entry.get("data") or {}).get("data", [])
            delays = [f for f in flights if f.get("departure", {}).get("delay") and f["departure"]["delay"] > 0]
            if delays:
                avg_delay = sum(f["departure"]["delay"] for f in delays) / len(delays)
                label, sev = _delay_severity(avg_delay)
                if sev > 0:
                    signals.append(
                        self.std_signal(
                            id=f"avstack-{icao}-{datetime.now(UTC).strftime('%Y%m%dT%H')}",
                            title=f"Aviation Delay: {icao} — {label}",
                            summary=f"Average departure delay {avg_delay:.0f} min across {len(delays)} flights",
                            domain="economics",
                            severity=sev,
                            india_score=15 if icao.startswith("VI") or icao.startswith("VO") else 5,
                            raw={"source": "aviationstack", "icao": icao, "avg_delay_min": round(avg_delay, 1)},
                            tags=["aviation", "delay", icao.lower()],
                        )
                    )

        # ICAO NOTAM closures
        if payload.get("notam") and isinstance(payload["notam"], list):
            for notam in payload["notam"]:
                text = (notam.get("message") or notam.get("all", "")).upper()
                if any(kw in text for kw in CLOSURE_KEYWORDS):
                    icao = notam.get("location", "")
                    signals.append(
                        self.std_signal(
                            id=f"notam-{icao}-{notam.get('id', '')}",
                            title=f"NOTAM Closure: {icao}",
                            summary=text[:300],
                            domain="defense",
                            severity=75,
                            india_score=15 if icao.startswith("VI") or icao.startswith("VO") or icao.startswith("OP") else 5,
                            raw={"source": "icao_notam", "icao": icao},
                            tags=["aviation", "notam", "closure", icao.lower()],
                        )
                    )
        return signals
