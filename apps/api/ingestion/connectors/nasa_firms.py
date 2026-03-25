"""Section 5 – NASA FIRMS Satellite Fire Detection (upgraded, 30-min poll)."""
from datetime import UTC, datetime

from ...config import settings
from ..base_connector import BaseConnector


class NASAFirmsConnector(BaseConnector):
    SOURCE_NAME = "nasa_firms"
    POLL_INTERVAL_SECONDS = 1800
    CACHE_TTL_SECONDS = 1800

    async def fetch(self):
        if not settings.NASA_FIRMS_KEY:
            return ""
        key = settings.NASA_FIRMS_KEY
        viirs_url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/world/1"
        modis_url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/MODIS_NRT/world/1"
        headers = {}
        if settings.NASA_EARTHDATA_TOKEN:
            headers["Authorization"] = f"Bearer {settings.NASA_EARTHDATA_TOKEN}"

        viirs = None
        modis = None
        try:
            viirs = await self.fetch_text(viirs_url, headers=headers)
        except Exception:
            pass
        try:
            modis = await self.fetch_text(modis_url, headers=headers)
        except Exception:
            pass
        return {"viirs": viirs, "modis": modis}

    async def parse(self, payload):
        if not payload:
            return []
        items = []
        for instrument, csv_text in payload.items():
            if not csv_text:
                continue
            lines = csv_text.splitlines()
            if len(lines) < 2:
                continue
            header = lines[0].split(",")
            col_map = {col.strip().lower(): i for i, col in enumerate(header)}
            lat_i = col_map.get("latitude", 0)
            lon_i = col_map.get("longitude", 1)
            conf_i = col_map.get("confidence")
            frp_i = col_map.get("frp")
            dn_i = col_map.get("daynight")
            acq_date_i = col_map.get("acq_date")

            for row in lines[1:201]:
                parts = row.split(",")
                if len(parts) < 3:
                    continue
                # Confidence filter
                confidence = _safe_float(parts[conf_i]) if conf_i is not None and conf_i < len(parts) else 100
                if confidence < 50:
                    continue
                lat = _safe_float(parts[lat_i])
                lon = _safe_float(parts[lon_i])
                frp = _safe_float(parts[frp_i]) if frp_i is not None and frp_i < len(parts) else 0
                daynight = parts[dn_i].strip() if dn_i is not None and dn_i < len(parts) else ""
                severity = min(100, int(frp / 10)) if frp else 30

                items.append(
                    self.std_signal(
                        id=f"firms-{instrument}-{parts[lat_i]}-{parts[lon_i]}-{parts[acq_date_i] if acq_date_i is not None and acq_date_i < len(parts) else ''}",
                        title=f"NASA FIRMS {instrument.upper()} hotspot (FRP={frp:.0f})",
                        summary=f"Fire detected at ({lat:.2f}, {lon:.2f}), confidence {confidence:.0f}%",
                        domain="climate",
                        severity=severity,
                        india_score=15 if lat and 6 < lat < 37 and lon and 68 < lon < 98 else 5,
                        raw={
                            "instrument": instrument,
                            "confidence": confidence,
                            "frp": frp,
                            "daynight": daynight,
                        },
                        tags=["wildfire", "nasa", instrument, daynight.lower()] if daynight else ["wildfire", "nasa", instrument],
                        latitude=lat,
                        longitude=lon,
                    )
                )
        return items


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None
