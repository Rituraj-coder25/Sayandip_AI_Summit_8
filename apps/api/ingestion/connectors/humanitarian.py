"""Section 11 – Humanitarian Data (HAPI, UNHCR, ReliefWeb, 1-hour poll)."""
from __future__ import annotations

from datetime import UTC, datetime

from ..base_connector import BaseConnector
from ...config import settings


class HumanitarianConnector(BaseConnector):
    SOURCE_NAME = "humanitarian_data"
    POLL_INTERVAL_SECONDS = 3600
    CACHE_TTL_SECONDS = 3600

    async def fetch(self):
        results: dict[str, object] = {}
        headers = {}
        if settings.HAPI_APP_IDENTIFIER:
            headers["X-HDX-HAPI-APP-IDENTIFIER"] = settings.HAPI_APP_IDENTIFIER
        # HAPI – refugees
        try:
            results["hapi_refugee"] = await self.fetch_json(
                "https://hapi.humdata.org/api/v1/population/refugee?output_format=json&limit=100",
                headers=headers,
            )
        except Exception:
            results["hapi_refugee"] = None
        # HAPI – IDPs
        try:
            results["hapi_idp"] = await self.fetch_json(
                "https://hapi.humdata.org/api/v1/population/idps?output_format=json&limit=100",
                headers=headers,
            )
        except Exception:
            results["hapi_idp"] = None
        # UNHCR
        try:
            results["unhcr"] = await self.fetch_json(
                "https://api.unhcr.org/population/v1/population/?limit=20&sortBy=total&sortOrder=desc"
            )
        except Exception:
            results["unhcr"] = None
        # ReliefWeb
        try:
            results["reliefweb"] = await self.fetch_json(
                "https://api.reliefweb.int/v1/reports?appname=goe&fields[include][]=title,body,date"
                "&filter[field]=type.name&filter[value]=Situation+Report&limit=20"
            )
        except Exception:
            results["reliefweb"] = None
        return results

    async def parse(self, payload) -> list[dict]:
        if not payload:
            return []
        signals: list[dict] = []

        # HAPI refugees
        if payload.get("hapi_refugee"):
            data = payload["hapi_refugee"].get("data", []) if isinstance(payload["hapi_refugee"], dict) else []
            for row in data[:30]:
                pop = int(row.get("population") or row.get("value") or 0)
                origin = row.get("origin_iso3") or row.get("origin") or "UNK"
                asylum = row.get("asylum_iso3") or row.get("asylum") or "UNK"
                if pop > 1_000_000:
                    severity = 80
                elif pop > 500_000:
                    severity = 60
                else:
                    severity = 40
                signals.append(
                    self.std_signal(
                        id=f"hapi-ref-{origin}-{asylum}",
                        title=f"Refugee Flow: {origin} → {asylum} ({pop:,})",
                        summary=f"{pop:,} refugees from {origin} in {asylum}",
                        domain="health",
                        severity=severity,
                        india_score=20 if origin in ("AFG", "MMR", "BGD", "LKA", "PAK") else 5,
                        raw={"type": "refugee", "origin": origin, "asylum": asylum, "population": pop},
                        tags=["humanitarian", "refugee", origin.lower()],
                    )
                )

        # HAPI IDPs
        if payload.get("hapi_idp"):
            data = payload["hapi_idp"].get("data", []) if isinstance(payload["hapi_idp"], dict) else []
            for row in data[:20]:
                pop = int(row.get("population") or row.get("value") or 0)
                country = row.get("location_iso3") or row.get("location") or "UNK"
                severity = 80 if pop > 1_000_000 else 60 if pop > 500_000 else 40
                signals.append(
                    self.std_signal(
                        id=f"hapi-idp-{country}",
                        title=f"Internal Displacement: {country} ({pop:,})",
                        summary=f"{pop:,} internally displaced persons in {country}",
                        domain="health",
                        severity=severity,
                        india_score=15 if country in ("IND", "PAK", "BGD", "MMR") else 5,
                        raw={"type": "idp", "country": country, "population": pop},
                        tags=["humanitarian", "idp", country.lower()],
                    )
                )

        # UNHCR
        if payload.get("unhcr"):
            entries = payload["unhcr"].get("items", []) if isinstance(payload["unhcr"], dict) else []
            for entry in entries[:10]:
                total = entry.get("total", 0) or 0
                country = entry.get("coo_name") or entry.get("coa_name") or "Unknown"
                severity = 80 if total > 1_000_000 else 60 if total > 500_000 else 40
                signals.append(
                    self.std_signal(
                        id=f"unhcr-{entry.get('year')}-{entry.get('coo')}-{entry.get('coa')}",
                        title=f"UNHCR: {int(total):,} displaced from {country}",
                        summary=f"Population of concern: {int(total):,} people",
                        domain="health",
                        severity=severity,
                        india_score=15 if "India" in country or "Pakistan" in country or "Bangladesh" in country or "Myanmar" in country else 5,
                        url="https://api.unhcr.org/population/v1/population/",
                        raw=entry,
                        tags=["unhcr", "displacement", "humanitarian"],
                    )
                )

        # ReliefWeb
        if payload.get("reliefweb"):
            reports = payload["reliefweb"].get("data", []) if isinstance(payload["reliefweb"], dict) else []
            for report in reports[:15]:
                fields = report.get("fields", {})
                title = (fields.get("title") or "ReliefWeb Report").strip()
                date = fields.get("date", {}).get("created") or datetime.now(UTC).isoformat()
                signals.append(
                    self.std_signal(
                        id=f"rw-{report.get('id', title[:20])}",
                        title=title[:120],
                        summary=f"ReliefWeb situation report",
                        domain="health",
                        severity=45,
                        india_score=5,
                        url=report.get("href", ""),
                        published_at=date,
                        raw={"source": "reliefweb"},
                        tags=["humanitarian", "reliefweb"],
                    )
                )

        return signals
