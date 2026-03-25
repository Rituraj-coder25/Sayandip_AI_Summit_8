"""
AntigravityQueryEngine - deterministic strategic question answering.

Builds grounded answers from recent intelligence items, graph tensions,
and rule-engine matches. It can optionally let an available LLM polish
the response, but it never requires one to produce an answer.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ...intelligence.classifier import DOMAINS
from ...ontology.graph_engine import OntologyGraphEngine
from .graph_reasoner import GraphReasoner

if TYPE_CHECKING:
    from .rule_engine import RuleMatch

logger = logging.getLogger("goe.antigravity.query")

INTENT_KEYWORDS = {
    "energy_security": ["energy", "oil", "crude", "lng", "hormuz", "petroleum", "fuel", "brent", "opec"],
    "strategic_risk": ["strategic risk", "critical risk", "nsa", "prime minister", "nsc", "threat", "recommend"],
    "geopolitical_risk": ["geopolit", "risk this week", "risk assessment", "week"],
    "external_shocks": ["shock", "72 hour", "48 hour", "watch", "monitor", "external"],
    "market_analysis": ["market", "economy", "nifty", "rupee", "inflation", "macro", "rbi", "inr"],
    "defense_risk": ["defense", "military", "border", "loc", "lac", "pakistan", "china", "missile"],
    "technology_risk": ["technology", "cyber", "chip", "semiconductor", "ai", "5g", "hack"],
    "climate_risk": ["climate", "earthquake", "flood", "storm", "seismic", "wildfire", "cyclone"],
}

INTENT_DOMAIN = {
    "market_analysis": "economics",
    "defense_risk": "defense",
    "technology_risk": "technology",
    "climate_risk": "climate",
}

ENERGY_KEYWORDS = ("oil", "crude", "brent", "wti", "hormuz", "gulf", "gas", "lng", "opec", "barrel")


class AntigravityQueryEngine:
    def __init__(self, redis, vector_store, neo4j_driver=None, db_factory=None, llm=None):
        self.redis = redis
        self.vector = vector_store
        self.neo4j = neo4j_driver
        self.db_factory = db_factory
        self.llm = llm

    def classify_intent(self, question: str) -> str:
        q = (question or "").lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(keyword in q for keyword in keywords):
                return intent
        return "general_assessment"

    async def answer(self, question: str, frontend_context: str = "") -> str:
        intent = self.classify_intent(question)
        snapshot = await self._load_snapshot()
        items, grouped, domain_risks, rule_matches, tensions = await self._load_reasoning_inputs()

        builders = {
            "energy_security": self._answer_energy_security,
            "strategic_risk": self._answer_strategic_risk,
            "geopolitical_risk": self._answer_geopolitical_risk,
            "external_shocks": self._answer_external_shocks,
        }
        builder = builders.get(intent, self._answer_general)
        deterministic = builder(question, intent, snapshot, items, grouped, domain_risks, rule_matches, tensions, frontend_context)

        if hasattr(self.llm, "complete") and getattr(self.llm, "_mode", "none") not in ("none", "detecting"):
            try:
                prompt = f"""Refine this GOE Antigravity answer for an Indian strategic analyst.
Keep the same structure, preserve all grounded facts, and stay under 800 words.
Do not invent additional sources or data.

QUESTION: {question}

ANTIGRAVITY ANSWER:
{deterministic}"""
                enhanced = await self.llm.complete(prompt, max_tokens=900, prefer_fast=True)
                if enhanced:
                    return enhanced
            except Exception as exc:
                logger.warning("LLM enhancement failed, using deterministic answer: %s", exc)

        return deterministic

    async def _load_snapshot(self) -> dict:
        snapshot = {
            "risk_score": 50,
            "risk_label": "MODERATE",
            "risk_color": "amber",
            "usd_inr": None,
            "nifty": None,
            "market_source": "",
            "signals_today": None,
        }
        if self.redis is None:
            return snapshot

        try:
            risk_raw = await self.redis.get("goe:india_risk_score_full")
            if risk_raw:
                risk = json.loads(risk_raw)
                snapshot["risk_score"] = int(risk.get("score") or snapshot["risk_score"])
                snapshot["risk_label"] = str(risk.get("label") or snapshot["risk_label"])
                snapshot["risk_color"] = str(risk.get("color") or snapshot["risk_color"])
        except Exception as exc:
            logger.warning("Unable to load India risk snapshot: %s", exc)

        try:
            market_raw = await self.redis.get("goe:market_snapshot")
            if market_raw:
                market = json.loads(market_raw)
                if isinstance(market.get("forex"), dict):
                    snapshot["usd_inr"] = market["forex"].get("INR")
                elif market.get("USDINR") is not None:
                    snapshot["usd_inr"] = market.get("USDINR")
                elif market.get("INR") is not None:
                    snapshot["usd_inr"] = market.get("INR")

                nifty = market.get("NIFTY")
                if isinstance(nifty, dict):
                    snapshot["nifty"] = nifty.get("value")
                else:
                    snapshot["nifty"] = nifty
                snapshot["market_source"] = str(market.get("source") or "GOE market snapshot")
        except Exception as exc:
            logger.warning("Unable to load market snapshot: %s", exc)

        try:
            processed = await self.redis.get("goe:stats:signals_today")
            if processed is not None:
                snapshot["signals_today"] = int(processed)
        except Exception:
            snapshot["signals_today"] = None

        return snapshot

    async def _load_reasoning_inputs(self) -> tuple[list, dict, dict, list, list]:
        grouped = {domain: [] for domain in DOMAINS}
        if self.db_factory is None:
            return [], grouped, {domain: 0 for domain in DOMAINS}, [], []

        items = []
        domain_risks = {domain: 0 for domain in DOMAINS}
        rule_matches: list = []
        tensions = []

        try:
            from .rule_engine import RuleEngine
            from .signal_aggregator import SignalAggregator

            aggregator = SignalAggregator(self.db_factory)
            items = await aggregator.fetch_recent(hours=24, limit=80)
            grouped = aggregator.group_by_domain(items)
            domain_risks = aggregator.compute_domain_risk(items)
            top_entities = aggregator.top_entities(items, n=8)

            if self.neo4j is not None and self.vector is not None and top_entities:
                reasoner = GraphReasoner(
                    graph_engine=OntologyGraphEngine(self.neo4j),
                    vector_store=self.vector,
                )
                tensions = await reasoner.analyse_entity_tensions(top_entities[:6])

            rule_matches = RuleEngine().evaluate(items, tensions)
        except Exception as exc:
            logger.warning("Antigravity query engine running without DB/graph enrichment: %s", exc)

        return items, grouped, domain_risks, rule_matches, tensions

    def _answer_energy_security(
        self,
        question: str,
        intent: str,
        snapshot: dict,
        items: list,
        grouped: dict,
        domain_risks: dict,
        rule_matches: list,
        tensions: list,
        frontend_context: str,
    ) -> str:
        economics = grouped.get("economics", [])
        defense = grouped.get("defense", [])
        energy_items = [item for item in economics + defense if any(word in self._item_blob(item) for word in ENERGY_KEYWORDS)]
        energy_rules = [rule for rule in rule_matches if rule.rule_id in {"r_oil_price_spike", "r_russia_ukraine_energy"}]
        impact_score = max(snapshot["risk_score"], max((rule.india_impact_score for rule in energy_rules), default=0), 60)

        lines = [
            "## ENERGY SECURITY - INDIA EXPOSURE ASSESSMENT",
            f"India Impact Score: {impact_score}/100 | Confidence: {'HIGH' if energy_rules or energy_items else 'MEDIUM'} | Freshness: LIVE",
            "",
            "Situation: India remains structurally exposed to oil and LNG disruptions because most crude demand is import-backed and Gulf shipping remains the main chokepoint.",
        ]
        if snapshot["usd_inr"] is not None:
            lines.append(f"Market pressure: USD/INR {snapshot['usd_inr']} | NIFTY {snapshot['nifty'] or 'n/a'}")
        lines.append("")
        lines.append("## LIVE SIGNALS")
        if energy_items:
            for item in energy_items[:4]:
                lines.append(self._format_item(item))
        else:
            lines.extend(self._context_fallback(frontend_context, "No backend energy signals were available at query time."))
        if energy_rules:
            rule = self._sort_rules(energy_rules)[0]
            lines.extend(
                [
                    "",
                    f"Rule-engine trigger: {rule.scenario_label} ({int(rule.base_probability * 100)}% baseline probability).",
                    f"Assessment: {rule.description}",
                ]
            )
        relevant_tensions = [t for t in tensions if t.domain_hint in {"economics", "defense"}][:3]
        if relevant_tensions:
            lines.append("")
            lines.append("## GRAPH TENSIONS")
            for tension in relevant_tensions:
                lines.append(self._format_tension(tension))
        recommendation = energy_rules[0].recommended_response if energy_rules else (
            "Lock in forward energy cover, monitor Hormuz-linked disruptions, and prepare RBI and oil-ministry contingency thresholds."
        )
        lines.extend(["", "## STRATEGIC RECOMMENDATION", recommendation])
        return "\n".join(lines)

    def _answer_strategic_risk(
        self,
        question: str,
        intent: str,
        snapshot: dict,
        items: list,
        grouped: dict,
        domain_risks: dict,
        rule_matches: list,
        tensions: list,
        frontend_context: str,
    ) -> str:
        priority_rules = self._sort_rules([rule for rule in rule_matches if rule.domain in {"geopolitics", "defense", "economics"}])
        lines = [
            "## STRATEGIC RISK - NSA ASSESSMENT FOR THE PRIME MINISTER",
            f"India Impact Score: {snapshot['risk_score']}/100 | Confidence: {'HIGH' if priority_rules else 'MEDIUM'} | Freshness: LIVE",
            "",
        ]
        if priority_rules:
            primary = priority_rules[0]
            lines.append(f"Primary assessed risk: {primary.scenario_label}.")
            lines.append(primary.description)
        else:
            lines.append("Primary assessed risk: no single dominant threat vector, but concurrent defense, geopolitical, and economic stresses remain active.")
        lines.extend(["", "## ACTIVE THREAT VECTORS"])
        if priority_rules:
            for index, rule in enumerate(priority_rules[:3], start=1):
                lines.append(f"{index}. {rule.scenario_label} | Impact {rule.india_impact_label} {rule.india_impact_score}/100")
                lines.append(f"   {rule.description}")
        else:
            for item in (grouped.get("defense", []) + grouped.get("geopolitics", []))[:3]:
                lines.append(self._format_item(item))
        if tensions:
            lines.extend(["", "## GRAPH CORROBORATION"])
            for tension in tensions[:3]:
                lines.append(self._format_tension(tension))
        recommendation = priority_rules[0].recommended_response if priority_rules else (
            "Maintain dual-front surveillance, preserve diplomatic back-channels, and tighten macro resilience monitoring."
        )
        lines.extend(["", "## NSA RECOMMENDATION", recommendation])
        return "\n".join(lines)

    def _answer_geopolitical_risk(
        self,
        question: str,
        intent: str,
        snapshot: dict,
        items: list,
        grouped: dict,
        domain_risks: dict,
        rule_matches: list,
        tensions: list,
        frontend_context: str,
    ) -> str:
        ranked_domains = sorted(
            [(domain, score) for domain, score in domain_risks.items() if score > 0],
            key=lambda pair: pair[1],
            reverse=True,
        )
        lines = [
            "## GEOPOLITICAL RISK ASSESSMENT - CURRENT WEEK",
            f"India Impact Score: {snapshot['risk_score']}/100 | Confidence: {'HIGH' if ranked_domains else 'MEDIUM'} | Freshness: LIVE",
            "",
            f"Situation: Weekly risk is being driven by {len(ranked_domains) or 1} active domains with top pressure in geopolitics, defense, and economics.",
            "",
            "## DOMAIN PRESSURE",
        ]
        if ranked_domains:
            for domain, score in ranked_domains[:4]:
                lines.append(f"- {domain.upper()}: {score}/100")
        else:
            lines.extend(self._context_fallback(frontend_context, "Backend domain scores were unavailable."))
        lines.extend(["", "## LIVE SIGNALS"])
        signals = grouped.get("geopolitics", [])[:3] + grouped.get("defense", [])[:2]
        if signals:
            for item in signals:
                lines.append(self._format_item(item))
        else:
            lines.extend(self._context_fallback(frontend_context, "No backend geopolitical signals were available at query time."))
        lines.extend([
            "",
            f"## TREND: {'ESCALATING' if snapshot['risk_score'] >= 65 else 'STABLE' if snapshot['risk_score'] >= 45 else 'DE-ESCALATING'}",
            "## STRATEGIC RECOMMENDATION",
            "Maintain maritime and border watch, keep economic signaling channels active, and verify any India-linked escalation before it hardens into policy action.",
        ])
        return "\n".join(lines)

    def _answer_external_shocks(
        self,
        question: str,
        intent: str,
        snapshot: dict,
        items: list,
        grouped: dict,
        domain_risks: dict,
        rule_matches: list,
        tensions: list,
        frontend_context: str,
    ) -> str:
        candidates = self._sort_rules(rule_matches)[:3]
        lines = [
            "## TOP 3 EXTERNAL SHOCKS - 72-HOUR WATCH",
            f"India Risk Score: {snapshot['risk_score']}/100 | Freshness: LIVE",
            "",
        ]
        if candidates:
            for index, rule in enumerate(candidates, start=1):
                lines.append(f"## SHOCK {index}: {rule.scenario_label.upper()}")
                lines.append(f"Composite Risk Score: {rule.india_impact_score}/100 | Probability: {int(rule.base_probability * 100)}%")
                lines.append(f"Impact: {rule.description}")
                if rule.matched_signals:
                    lines.append("Trigger signals:")
                    for title in rule.matched_signals[:2]:
                        lines.append(f"- {title}")
                lines.append(f"Recommendation: {rule.recommended_response}")
                lines.append("")
        else:
            lines.extend(self._context_fallback(frontend_context, "No high-confidence backend shock candidates were available."))
            lines.extend([
                "",
                "Fallback shocks to monitor:",
                "- Energy supply disruption and INR stress",
                "- Military escalation in India's extended neighborhood",
                "- Climate or logistics disruption in regional trade corridors",
            ])
        return "\n".join(lines).rstrip()

    def _answer_general(
        self,
        question: str,
        intent: str,
        snapshot: dict,
        items: list,
        grouped: dict,
        domain_risks: dict,
        rule_matches: list,
        tensions: list,
        frontend_context: str,
    ) -> str:
        domain = INTENT_DOMAIN.get(intent, "geopolitics")
        signals = grouped.get(domain, [])[:5]
        lines = [
            f"## {domain.upper()} - GOE LIVE ASSESSMENT",
            f"India Impact Score: {snapshot['risk_score']}/100 | Freshness: LIVE | Signals: {len(signals)} in {domain}",
            "",
            f'Query: "{question}"',
            "",
        ]
        if signals:
            lines.append("## LIVE SIGNAL CONTEXT")
            for item in signals:
                lines.append(self._format_item(item))
        else:
            lines.extend(self._context_fallback(frontend_context, "No backend domain signals were available at query time."))
        if rule_matches:
            lines.extend(["", "## RULE-ENGINE ASSESSMENT"])
            for rule in self._sort_rules(rule_matches)[:2]:
                lines.append(f"- {rule.scenario_label}: {rule.description}")
        lines.extend([
            "",
            "## INDIA RISK SNAPSHOT",
            f"Overall Risk Score: {snapshot['risk_score']}/100 ({snapshot['risk_label']})",
        ])
        if snapshot["usd_inr"] is not None:
            lines.append(f"USD/INR: {snapshot['usd_inr']}")
        if snapshot["nifty"] is not None:
            lines.append(f"NIFTY 50: {snapshot['nifty']}")
        lines.extend([
            "",
            f"GOE Antigravity engine - deterministic, graph-aware, and grounded in live signals collected up to {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        ])
        return "\n".join(lines)

    def _sort_rules(self, rules: list) -> list:
        return sorted(
            rules,
            key=lambda rule: (rule.india_impact_score * rule.base_probability, rule.india_impact_score, rule.base_probability),
            reverse=True,
        )

    def _context_fallback(self, frontend_context: str, empty_message: str) -> list[str]:
        lines = [empty_message]
        excerpt = self._frontend_excerpt(frontend_context)
        if excerpt:
            lines.append("Frontend context:")
            lines.extend(f"- {line}" for line in excerpt)
        return lines

    def _frontend_excerpt(self, frontend_context: str, limit: int = 6) -> list[str]:
        if not frontend_context:
            return []
        lines = []
        for raw in frontend_context.splitlines():
            line = raw.strip()
            if not line or line.startswith("==="):
                continue
            lines.append(line)
            if len(lines) >= limit:
                break
        return lines

    def _format_item(self, item) -> str:
        return (
            f"- [{item.source_name} | {str(item.domain).upper()} | Sev:{item.severity or 0} | "
            f"India:{item.india_score or 0}] {item.title}"
        )

    def _format_tension(self, tension) -> str:
        return (
            f"- {tension.source_entity} -> {tension.target_entity} [{tension.relation_type}] "
            f"score {tension.tension_score:.1f}"
        )

    def _item_blob(self, item) -> str:
        return f"{item.title or ''} {item.summary or ''}".lower()
