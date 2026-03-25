"""
Generates multi-branch geopolitical probability trees.
Returns a plain dict tree so routers can serialise it directly.

Supports two paths:
  1. Antigravity (deterministic graph + rule engine) — when Neo4j + db available
  2. LLM fallback — when Ollama/Anthropic configured
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("goe.scenario")


class ScenarioEngine:
    def __init__(self, llm, redis_client, vector_store, neo4j_driver=None, db_factory=None):
        self._llm = llm
        self._redis = redis_client
        self._vector = vector_store
        self._neo4j = neo4j_driver
        self._db_factory = db_factory

    async def generate_scenario_tree(self, hypothesis: str, depth: int = 3) -> dict:
        # Try Antigravity path first
        if self._neo4j is not None and self._db_factory is not None:
            try:
                return await self._antigravity_tree(hypothesis)
            except Exception as exc:
                logger.error("Antigravity scenario generation failed, falling back to LLM: %s", exc)

        # Fall back to LLM path
        if self._llm and self._llm._mode != "none":
            return await self._llm_tree(hypothesis)

        return self._fallback_tree(hypothesis)

    async def _antigravity_tree(self, hypothesis: str) -> dict:
        from .antigravity.graph_reasoner import GraphReasoner
        from .antigravity.signal_aggregator import SignalAggregator
        from .antigravity.rule_engine import RuleEngine
        from .antigravity.scenario_builder import ScenarioBuilder
        from ..ontology.graph_engine import OntologyGraphEngine

        aggregator = SignalAggregator(self._db_factory)
        items = await aggregator.fetch_recent(hours=72, limit=150)

        reasoner = GraphReasoner(OntologyGraphEngine(self._neo4j), self._vector)
        entities = [word for word in hypothesis.lower().split() if len(word) > 3]
        tensions = await reasoner.analyse_entity_tensions(entities[:6])

        rule_engine = RuleEngine()
        builder = ScenarioBuilder(reasoner, rule_engine)
        return await builder.build_scenario_tree(hypothesis, items, tensions)

    async def _llm_tree(self, hypothesis: str) -> dict:
        """Original LLM-based scenario generation (extracted from old generate_scenario_tree)."""
        hits = self._vector.query(hypothesis, n_results=5)
        context_lines = [f"- {item['document'][:150]}" for item in hits]
        rag_ctx = "\n".join(context_lines) or "No similar historical events found."

        prompt = f"""You are GOE-1 Scenario Engine. Analyse this geopolitical hypothesis.

HYPOTHESIS: {hypothesis}

HISTORICAL CONTEXT FROM GOE KNOWLEDGE BASE:
{rag_ctx}

Generate a realistic probability tree. Return ONLY valid JSON - no markdown.

{{
  "hypothesis": "{hypothesis}",
  "timeline": "when this crystallises (e.g. '2-4 weeks')",
  "confidence": 65,
  "branches": [
    {{
      "id": "branch_a",
      "label": "Branch A - [short descriptive name]",
      "probability": 45,
      "india_impact_score": 78,
      "india_impact": "CRITICAL",
      "india_effects": ["specific effect 1", "specific effect 2"],
      "timeline": "72 hours",
      "key_actors": ["actor1", "actor2"],
      "recommended_response": "specific action India should take",
      "historical_analog": "Similar to: [real event, year]",
      "sub_branches": []
    }},
    {{
      "id": "branch_b",
      "label": "Branch B - [name]",
      "probability": 35,
      "india_impact_score": 45,
      "india_impact": "HIGH",
      "india_effects": ["effect"],
      "timeline": "2 weeks",
      "key_actors": ["actor"],
      "recommended_response": "action",
      "historical_analog": "Similar to: [event]",
      "sub_branches": []
    }},
    {{
      "id": "branch_c",
      "label": "Branch C - [name]",
      "probability": 20,
      "india_impact_score": 30,
      "india_impact": "MEDIUM",
      "india_effects": ["effect"],
      "timeline": "3 months",
      "key_actors": ["actor"],
      "recommended_response": "action",
      "historical_analog": "Similar to: [event]",
      "sub_branches": []
    }}
  ],
  "india_net_assessment": "2-sentence summary of what this means for India overall."
}}

Probabilities must sum to 100. Be specific - no vague statements."""

        raw = await self._llm.complete(prompt, max_tokens=2000)
        if not raw:
            return self._fallback_tree(hypothesis)

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]

        try:
            tree = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                return self._fallback_tree(hypothesis)
            try:
                tree = json.loads(match.group())
            except Exception:
                return self._fallback_tree(hypothesis)

        tree["generated_at"] = datetime.now(timezone.utc).isoformat()
        tree.setdefault("id", str(uuid.uuid4()))
        return tree

    def _fallback_tree(self, hypothesis: str) -> dict:
        return {
            "hypothesis": hypothesis,
            "error": "Scenario generation failed - LLM unavailable",
            "branches": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }