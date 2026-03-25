"""
ScenarioBuilder — builds structured scenario trees from rule engine output.
This replaces the LLM-based ScenarioEngine path. No LLM calls.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from ....models.intelligence import IntelligenceItem
from .graph_reasoner import GraphReasoner, TensionSignal
from .rule_engine import RuleEngine, RuleMatch

logger = logging.getLogger("goe.antigravity.scenario_builder")


class ScenarioBuilder:
    def __init__(self, graph_reasoner: GraphReasoner, rule_engine: RuleEngine):
        self.reasoner = graph_reasoner
        self.rules = rule_engine

    async def build_scenario_tree(
        self,
        hypothesis: str,
        items: list[IntelligenceItem],
        tension_signals: list[TensionSignal],
    ) -> dict:
        # 1. Filter items and tensions relevant to hypothesis via keyword overlap
        tokens = [t.lower() for t in hypothesis.split() if len(t) >= 4]

        filtered_items = items
        filtered_tensions = tension_signals

        if tokens:
            filtered_items = [
                item for item in items
                if any(
                    tok in f"{item.title or ''} {item.summary or ''}".lower()
                    for tok in tokens
                )
            ]
            filtered_tensions = [
                t for t in tension_signals
                if any(
                    tok in f"{t.source_entity} {t.target_entity} {t.relation_type}".lower()
                    for tok in tokens
                )
            ]

        # If filtering yields nothing, fall back to all data
        if not filtered_items:
            filtered_items = items
        if not filtered_tensions:
            filtered_tensions = tension_signals

        # 2. Run rule evaluation
        rule_matches = self.rules.evaluate(filtered_items, filtered_tensions)

        # 3. Fallback if no rules fire
        if len(rule_matches) == 0:
            fallback = RuleMatch(
                rule_id="r_fallback",
                rule_name="Insufficient Signal",
                matched_entities=[],
                matched_signals=[],
                domain="geopolitics",
                base_probability=0.5,
                india_impact_score=30,
                india_impact_label="LOW",
                scenario_label="Situation remains ambiguous",
                description="Insufficient corroborating signals in the knowledge graph to generate a high-confidence scenario tree for this hypothesis. Monitor for 24–48 hours.",
                recommended_response="Maintain current monitoring posture. No immediate action recommended.",
                wildcard=False,
                confidence_multiplier=0.3,
            )
            rule_matches = [fallback]

        # 4. Separate main vs wildcard
        main_branches = sorted(
            [m for m in rule_matches if not m.wildcard],
            key=lambda m: m.india_impact_score,
            reverse=True,
        )[:3]

        wildcard_branches = [m for m in rule_matches if m.wildcard][:2]

        # 5. Normalize probabilities for main branches
        total_prob = sum(m.base_probability for m in main_branches) or 1.0
        normalized_probs = [
            max(1, int((m.base_probability / total_prob) * 100)) for m in main_branches
        ]
        # Adjust to sum to 100
        if normalized_probs:
            diff = 100 - sum(normalized_probs)
            normalized_probs[0] += diff

        # 6. India net assessment
        top_domain = main_branches[0].domain if main_branches else "geopolitics"
        top_score = main_branches[0].india_impact_score if main_branches else 30
        label = main_branches[0].india_impact_label if main_branches else "LOW"
        assessment = (
            f"The most likely scenario involves {top_domain}-domain risk with {label} India impact "
            f"(score: {top_score}/100). "
            f"{len(rule_matches)} rule-based branches identified from {len(filtered_items)} active signals "
            f"and {len(tension_signals)} graph tension edges."
        )

        # 7. Timeline estimate
        max_severity = 0
        for m in rule_matches:
            for item in filtered_items:
                if (item.severity or 0) > max_severity:
                    max_severity = item.severity or 0
        if max_severity >= 70:
            timeline_estimate = "24–72 hours"
        elif max_severity >= 50:
            timeline_estimate = "3–7 days"
        else:
            timeline_estimate = "1–3 weeks"

        # 8. Build output dict
        branches_output = []
        for i, m in enumerate(main_branches):
            prob = normalized_probs[i] if i < len(normalized_probs) else 0
            branches_output.append({
                "id": f"branch_{chr(ord('a') + i)}",
                "label": f"Branch {chr(ord('A') + i)} — {m.scenario_label}",
                "probability": prob,
                "india_impact_score": m.india_impact_score,
                "india_impact": m.india_impact_label,
                "india_effects": [m.description],
                "timeline": timeline_estimate,
                "key_actors": m.matched_entities[:5],
                "recommended_response": m.recommended_response,
                "historical_analog": await self._get_analog(m),
                "sub_branches": [],
                "wildcard": False,
                "antigravity": True,
                "rule_id": m.rule_id,
                "corroborating_signals": m.matched_signals[:3],
            })

        for i, w in enumerate(wildcard_branches):
            branches_output.append({
                "id": f"wildcard_{i}",
                "label": f"Wildcard — {w.scenario_label}",
                "probability": int(w.base_probability * 100),
                "india_impact_score": w.india_impact_score,
                "india_impact": w.india_impact_label,
                "india_effects": [w.description],
                "timeline": "Indeterminate",
                "key_actors": w.matched_entities[:3],
                "recommended_response": w.recommended_response,
                "historical_analog": await self._get_analog(w),
                "sub_branches": [],
                "wildcard": True,
                "antigravity": True,
                "rule_id": w.rule_id,
            })

        return {
            "hypothesis": hypothesis,
            "timeline": timeline_estimate,
            "confidence": int(main_branches[0].base_probability * 100) if main_branches else 30,
            "branches": branches_output,
            "india_net_assessment": assessment,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4()),
            "source": "antigravity",
            "signal_count": len(filtered_items),
            "tension_edge_count": len(tension_signals),
        }

    async def _get_analog(self, match: RuleMatch) -> str:
        try:
            query_text = " ".join(match.matched_signals[:2]) if match.matched_signals else match.scenario_label
            results = self.reasoner.vector.query(query_text, n_results=1)
            if results:
                return f"Similar to: {results[0]['document'][:80]}"
        except Exception:
            pass
        return f"Rule: {match.rule_name} (no historical analog found)"
