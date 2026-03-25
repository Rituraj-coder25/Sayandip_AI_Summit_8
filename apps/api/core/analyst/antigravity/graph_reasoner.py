"""
GraphReasoner — traverses the Neo4j knowledge graph to extract tension signals
and historical analogs from ChromaDB. No LLM calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ...ontology.graph_engine import OntologyGraphEngine
from ...intelligence.vector_store import GOEVectorStore

logger = logging.getLogger("goe.antigravity.graph_reasoner")

TENSION_MULTIPLIER = {
    "ATTACKED": 3.5,
    "SANCTIONED": 2.8,
    "THREATENED": 2.5,
    "DISPUTED": 2.2,
    "RELATED_TO": 1.0,
    "TRADES_WITH": 0.8,
    "ENGAGED": 0.9,
    "NEAR": 1.1,
}

DOMAIN_KEYWORDS = {
    "defense": [
        "attack", "military", "missile", "troops", "army", "navy", "nuclear",
        "bomb", "weapon", "drone", "airforce", "irgc", "nato", "pla", "isi",
    ],
    "economics": [
        "trade", "sanction", "tariff", "oil", "gas", "export", "import", "bank",
        "inflation", "gdp", "currency", "market", "investment", "debt",
    ],
    "geopolitics": [
        "border", "summit", "election", "president", "minister", "diplomacy",
        "un", "treaty", "ceasefire", "coup", "protest", "referendum",
    ],
    "technology": [
        "cyber", "hack", "satellite", "ai", "chip", "semiconductor", "space",
        "infrastructure", "grid", "telecom", "5g",
    ],
    "climate": [
        "earthquake", "flood", "fire", "hurricane", "drought", "tsunami",
        "seismic", "climate", "storm", "volcano",
    ],
}


@dataclass
class TensionSignal:
    source_entity: str
    target_entity: str
    relation_type: str
    tension_score: float
    mention_count: int
    strength: float
    domain_hint: str = ""


class GraphReasoner:
    def __init__(self, graph_engine: OntologyGraphEngine, vector_store: GOEVectorStore):
        self.graph = graph_engine
        self.vector = vector_store

    async def analyse_entity_tensions(self, entity_names: list[str]) -> list[TensionSignal]:
        if not entity_names:
            return []

        all_tensions: list[TensionSignal] = []

        for entity_name in entity_names:
            try:
                neighborhood = await self.graph.get_entity_neighborhood(entity_name, depth=2)
            except Exception as exc:
                logger.warning("Graph query failed for '%s': %s", entity_name, exc)
                continue

            for link in neighborhood.get("links", []):
                rel_type = (link.get("type") or "RELATED_TO").upper()
                strength = float(link.get("strength") or 0.3)
                mentions = int(link.get("mentions") or 1)
                multiplier = TENSION_MULTIPLIER.get(rel_type, 1.0)
                tension_score = strength * mentions * multiplier

                signal = TensionSignal(
                    source_entity=link.get("source", entity_name),
                    target_entity=link.get("target", ""),
                    relation_type=rel_type,
                    tension_score=tension_score,
                    mention_count=mentions,
                    strength=strength,
                )
                signal.domain_hint = self.classify_tension_domain(signal)
                all_tensions.append(signal)

        all_tensions.sort(key=lambda t: t.tension_score, reverse=True)
        return all_tensions

    def classify_tension_domain(self, tension: TensionSignal) -> str:
        combined = (
            f"{tension.source_entity} {tension.target_entity} {tension.relation_type}"
        ).lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                return domain
        return "geopolitics"

    async def get_historical_analogs(
        self, query_text: str, domain: str, n: int = 3
    ) -> list[dict]:
        try:
            return self.vector.query(query_text, n_results=n, where={"domain": domain})
        except Exception:
            return self.vector.query(query_text, n_results=n)

    async def compute_india_exposure(self, tension_signals: list[TensionSignal]) -> float:
        if not tension_signals:
            return 0.0

        from ...intelligence.india_scorer import IndiaRelevanceScorer

        scorer = IndiaRelevanceScorer()
        scores: list[int] = []
        for tension in tension_signals:
            text = f"{tension.source_entity} {tension.target_entity}"
            score = scorer.score(text, entities=[])
            scores.append(score)

        if not scores:
            return 0.0
        return max(0.0, min(100.0, sum(scores) / len(scores)))
