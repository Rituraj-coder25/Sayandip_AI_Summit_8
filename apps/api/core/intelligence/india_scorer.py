from __future__ import annotations

import math
import re

try:
    from geopy.distance import geodesic
except Exception:
    geodesic = None

INDIA_CENTER = (20.5937, 78.9629)
NEIGHBORS = {"pakistan", "china", "bangladesh", "nepal", "bhutan", "myanmar", "sri lanka", "afghanistan", "maldives"}
PARTNERS = {"united states", "russia", "israel", "france", "uae", "japan", "australia", "united kingdom"}
ADVERSARIES = {"pakistan army", "isi", "pla", "plan", "irgc", "taliban", "ttp", "lashkar", "jaish", "hamas", "hezbollah"}
INDIA_RE = re.compile(
    r"\b(india|indian|modi|delhi|new delhi|mumbai|kolkata|chennai|bengaluru|rbi|isro|drdo|nifty|sensex|rupee|loc|lac|kashmir|arunachal|aksi chin|depsang|jaishankar|rajnath|indian ocean|bay of bengal|arabian sea|quad|brics|sco|g20 india)\b",
    re.IGNORECASE,
)


class IndiaRelevanceScorer:
    def score(
        self,
        text: str,
        entities: list[dict] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> int:
        score = 0
        lower = (text or "").lower()
        entities = entities or []
        entity_texts = {entity.get("text", "").lower() for entity in entities}

        matches = INDIA_RE.findall(lower)
        if matches:
            score += 25
        if len(matches) >= 3:
            score += 10

        lat = lat if lat is not None else latitude
        lon = lon if lon is not None else longitude
        if lat is not None and lon is not None:
            try:
                distance = _distance_from_india(lat, lon)
                if distance < 500:
                    score += 40
                elif distance < 1500:
                    score += 20
                elif distance < 3000:
                    score += 10
            except Exception:
                pass

        if any(name in lower or name in entity_texts for name in NEIGHBORS):
            score += 18
        if any(name in lower or name in entity_texts for name in PARTNERS):
            score += 8
        if any(name in lower for name in ADVERSARIES):
            score += 28

        global_keywords = ["oil price", "opec", "nuclear", "world war", "pandemic", "dollar", "fed rate", "imf", "world bank"]
        if any(keyword in lower for keyword in global_keywords):
            score += 12

        return min(100, score)


def _distance_from_india(lat: float, lon: float) -> float:
    if geodesic is not None:
        return float(geodesic(INDIA_CENTER, (lat, lon)).km)

    lat1, lon1 = map(math.radians, INDIA_CENTER)
    lat2, lon2 = math.radians(lat), math.radians(lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))