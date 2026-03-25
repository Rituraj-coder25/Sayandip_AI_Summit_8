"""
BriefAssembler — formats the structured GOE Daily Brief from aggregated data.
Pure string-template assembly, no LLM calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ....models.intelligence import IntelligenceItem
from .graph_reasoner import TensionSignal

logger = logging.getLogger("goe.antigravity.brief_assembler")

RISK_BASELINE = 50
DOMAINS_ORDERED = ["geopolitics", "economics", "defense", "technology", "climate"]


@dataclass
class BriefContext:
    date_str: str
    india_risk: dict  # {"score": int, "label": str, "color": str}
    market: dict  # {"USDINR": str, ...} from Redis
    domain_groups: dict  # {domain: [IntelligenceItem]}
    domain_risks: dict  # {domain: int}
    tension_signals: list  # list[TensionSignal]
    top_entities: list  # list[str]
    entity_counts: dict  # {entity: count}
    scenario_branches: list  # list[dict] from ScenarioBuilder
    total_signal_count: int
    india_exposure: float


class BriefAssembler:
    def __init__(self):
        pass

    def assemble(self, context: BriefContext) -> tuple[str, dict]:
        c = context
        now = datetime.now(timezone.utc)
        full_date = now.strftime("%A, %d %B %Y")
        generated_at = now.strftime("%Y-%m-%d %H:%M UTC")

        india_risk_score = c.india_risk.get("score", 50)
        india_risk_label = c.india_risk.get("label", "MODERATE")

        # Executive summary — top 3 items by severity
        all_items = []
        for items in c.domain_groups.values():
            all_items.extend(items)
        all_items.sort(key=lambda x: (x.severity or 0), reverse=True)
        top3 = all_items[:3]
        if top3:
            titles = ". ".join((item.title or "No title")[:100] for item in top3)
            executive_summary = f"Key developments: {titles}. India exposure score: {c.india_exposure:.0f}/100."
        else:
            executive_summary = "No significant intelligence signals in the past 24 hours. All domains quiet."

        # Risk trend
        top_domain = self._top_domain(c.domain_risks)
        if india_risk_score > 65:
            risk_trend = f"ESCALATING — {top_domain} domain driving risk elevation"
        elif india_risk_score > 45:
            risk_trend = f"STABLE — monitor {top_domain} for directional change"
        else:
            risk_trend = "DE-ESCALATING — signal volume below baseline"

        # Priority action
        if c.scenario_branches:
            sorted_branches = sorted(
                c.scenario_branches,
                key=lambda b: b.get("india_impact_score", 0),
                reverse=True,
            )
            priority_action = sorted_branches[0].get(
                "recommended_response",
                "Maintain standard monitoring posture across all domains.",
            )
        else:
            priority_action = "Maintain standard monitoring posture across all domains."

        # Key opportunity
        top_entity = c.top_entities[0] if c.top_entities else "unspecified"
        if c.india_exposure > 60:
            key_opportunity = f"Diplomatic positioning window open around {top_entity} developments."
        elif top_domain == "economics":
            key_opportunity = f"Potential energy import arbitrage as {top_entity} supply signals shift."
        else:
            key_opportunity = "No high-confidence opportunity identified in current signal window."

        # Domain sections
        domain_sections = {}
        for domain in DOMAINS_ORDERED:
            items = c.domain_groups.get(domain, [])
            if items:
                lines = []
                for item in items[:2]:
                    sev = item.severity or 0
                    iscore = item.india_score or 0
                    src = item.source_name or "unknown"
                    title = item.title or "Untitled"
                    summary = (item.summary or "No details available.")[:200]
                    lines.append(
                        f"[{src} | Sev:{sev} | India:{iscore}] {title}\n  → {summary}"
                    )
                domain_sections[domain] = "\n".join(lines)
            else:
                domain_sections[domain] = "No significant signals in this domain in the past 24 hours."

        # Threat matrix
        def _risk_label(score: int) -> str:
            if score >= 70:
                return "HIGH"
            elif score >= 40:
                return "MED"
            return "LOW"

        def _trend(score: int) -> str:
            if score > 60:
                return "UP"
            elif score >= 40:
                return "FLAT"
            return "DOWN"

        threat_rows = []
        domain_display = {
            "geopolitics": "Geopolitics",
            "economics": "Economics",
            "defense": "Defense",
            "technology": "Technology",
            "climate": "Climate",
        }
        for domain in DOMAINS_ORDERED:
            risk = c.domain_risks.get(domain, 0)
            threat_rows.append(
                f"{domain_display[domain]:12s} | {_risk_label(risk):4s}       | {risk:3d}/100     | {_trend(risk)}"
            )
        threat_matrix = "\n".join(threat_rows)

        # Scenario branches text
        scenario_lines = []
        for i, branch in enumerate(c.scenario_branches[:3]):
            letter = chr(ord("A") + i)
            prob = branch.get("probability", "?")
            label = branch.get("label", "Unknown")
            impact_label = branch.get("india_impact", "UNKNOWN")
            impact_score = branch.get("india_impact_score", 0)
            desc = branch.get("india_effects", ["No description"])[0] if branch.get("india_effects") else "No description"
            resp = branch.get("recommended_response", "No response specified.")
            scenario_lines.append(
                f"Branch {letter} ({prob}%) — {label}\n"
                f"  India impact: {impact_label} ({impact_score}/100)\n"
                f"  {desc}\n"
                f"  Response: {resp}"
            )
        scenario_text = "\n\n".join(scenario_lines) if scenario_lines else "No scenario branches generated from current signal data."

        # Strategic priorities
        priorities_lines = []
        seen_domains = set()
        for branch in sorted(
            c.scenario_branches,
            key=lambda b: b.get("india_impact_score", 0),
            reverse=True,
        ):
            domain = branch.get("label", "").split("—")[0].strip().lower() if "—" in branch.get("label", "") else "general"
            if domain not in seen_domains and len(priorities_lines) < 3:
                seen_domains.add(domain)
                priorities_lines.append(
                    f"{len(priorities_lines) + 1}. {branch.get('recommended_response', 'Monitor developments.')}"
                )
        while len(priorities_lines) < 3:
            fill_domain = DOMAINS_ORDERED[len(priorities_lines)] if len(priorities_lines) < len(DOMAINS_ORDERED) else "all"
            priorities_lines.append(
                f"{len(priorities_lines) + 1}. Monitor {fill_domain} domain signals for directional change over the next 72 hours."
            )
        priorities = "\n".join(priorities_lines)

        # Entities to watch
        entities_lines = []
        for entity in c.top_entities[:5]:
            count = c.entity_counts.get(entity, 0)
            # Determine domain for entity — find domain of highest-severity item containing it
            entity_domain = "geopolitics"
            for item in all_items:
                ents = item.entities or []
                for e in ents:
                    ename = e.get("text", "") if isinstance(e, dict) else str(e)
                    if ename == entity:
                        entity_domain = item.domain or "geopolitics"
                        break
            entities_lines.append(
                f"- {entity}: Appearing in {count} signals across {entity_domain} domain. Monitor for escalation."
            )
        entities_to_watch = "\n".join(entities_lines) if entities_lines else "- No high-frequency entities detected in current signal window."

        tension_edge_count = len(c.tension_signals)

        brief_text = f"""--- GOE DAILY STRATEGIC INTELLIGENCE BRIEF (ANTIGRAVITY) ---
Date: {full_date}
Classification: FOR AUTHORISED PERSONNEL ONLY
India Risk Score: {india_risk_score}/100 — {india_risk_label}
Signal Sources: {c.total_signal_count} active signals | Graph Edges: {tension_edge_count}
Engine: Antigravity Rule Engine v1.0 (no LLM)

EXECUTIVE SUMMARY
{executive_summary}

INDIA STRATEGIC UPDATE
- Risk trend: {risk_trend}
- Priority action item: {priority_action}
- Key opportunity: {key_opportunity}

[GEOPOLITICS]
{domain_sections['geopolitics']}

[ECONOMICS]
{domain_sections['economics']}

[DEFENSE]
{domain_sections['defense']}

[TECHNOLOGY]
{domain_sections['technology']}

[CLIMATE]
{domain_sections['climate']}

THREAT MATRIX
Domain       | Risk Level | India Impact | Trend
{threat_matrix}

SCENARIO BRANCHES (from knowledge graph)
{scenario_text}

STRATEGIC PRIORITIES FOR INDIA (Next 7 days)
{priorities}

ENTITIES TO WATCH
{entities_to_watch}

--- END OF BRIEF ---
Generated: {generated_at} | GOE Antigravity v1.0"""

        sections = self._build_sections_dict(context)
        return brief_text, sections

    def _build_sections_dict(self, context: BriefContext) -> dict:
        return {
            "engine": "antigravity_v1",
            "domain_risks": context.domain_risks,
            "top_entities": context.top_entities[:10],
            "tension_edge_count": len(context.tension_signals),
            "scenario_count": len(context.scenario_branches),
            "signal_count": context.total_signal_count,
            "india_exposure": context.india_exposure,
        }

    @staticmethod
    def _top_domain(domain_risks: dict) -> str:
        if not domain_risks:
            return "geopolitics"
        return max(domain_risks, key=domain_risks.get)
