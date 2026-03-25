"""
Generates the GOE Daily Strategic Brief at 06:00 IST and on-demand.

Supports two generation paths:
  1. Antigravity (deterministic graph + rule engine) — used when Neo4j + ChromaDB available
  2. LLM fallback — used when Ollama/Anthropic is configured
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.daily_brief import DailyBrief
from ...models.intelligence import IntelligenceItem

logger = logging.getLogger("goe.daily_brief")

BRIEF_SYSTEM = """You are GOE-1 generating the official Daily Strategic Intelligence Brief.
Write in the style of a classified government intelligence briefing.
Be concise, factual, and specific. No filler words. Short declarative sentences.
Every claim must reference actual signals from the context provided."""


class DailyBriefGenerator:
    def __init__(self, redis_client, llm, neo4j_driver=None, vector_store=None, db_factory=None):
        self.redis = redis_client
        self.llm = llm
        self._neo4j = neo4j_driver
        self._vector = vector_store
        self._db_factory = db_factory

    async def generate(self, db: AsyncSession) -> DailyBrief:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check for existing brief
        existing = await db.execute(select(DailyBrief).where(DailyBrief.date == today))
        brief = existing.scalar_one_or_none()

        content = None
        sections = {}
        india_score = 50
        model_used = "none"

        # --- ANTIGRAVITY PATH (no LLM required) ---
        if self._neo4j is not None and self._vector is not None:
            try:
                content, sections, india_score = await self._generate_antigravity(db, today)
                model_used = "antigravity_v1"
            except Exception as exc:
                logger.error("Antigravity brief generation failed, falling back to LLM: %s", exc)
                content = None  # fall through to LLM path

        # --- LLM FALLBACK (existing behaviour, unchanged) ---
        if content is None and self.llm and self.llm._mode != "none":
            try:
                content, sections, india_score = await self._generate_llm(db, today)
                model_used = self.llm._mode
            except Exception as exc:
                logger.error("LLM brief generation failed: %s", exc)
                content = None

        # --- LAST RESORT ---
        if content is None:
            content = "Brief generation unavailable: no knowledge graph and no LLM configured."
            sections = {}
            india_score = 50
            model_used = "none"

        # Persist
        if brief is None:
            brief = DailyBrief(
                id=str(uuid.uuid4()),
                date=today,
                content=content,
                sections=sections,
                india_score=india_score,
                model_used=model_used,
            )
            db.add(brief)
        else:
            brief.content = content
            brief.sections = sections
            brief.india_score = india_score
            brief.model_used = model_used

        await db.flush()

        # Redis pub/sub
        await self.redis.setex(
            "goe:latest_daily_brief",
            86400,
            json.dumps({"id": brief.id, "date": today, "content": content}),
        )
        await self.redis.publish(
            "goe:daily_brief_ready",
            json.dumps({"type": "DAILY_BRIEF_READY", "date": today, "brief_id": brief.id}),
        )
        logger.info("Daily brief generated for %s: %s (engine=%s)", today, brief.id, model_used)
        return brief

    async def _generate_antigravity(self, db, today: str) -> tuple[str, dict, int]:
        from .antigravity.graph_reasoner import GraphReasoner
        from .antigravity.signal_aggregator import SignalAggregator
        from .antigravity.rule_engine import RuleEngine
        from .antigravity.scenario_builder import ScenarioBuilder
        from .antigravity.brief_assembler import BriefAssembler, BriefContext
        from ..ontology.graph_engine import OntologyGraphEngine

        # 1. Fetch and group recent signals
        aggregator = SignalAggregator(self._db_factory)
        items = await aggregator.fetch_recent(hours=24, limit=100)
        grouped = aggregator.group_by_domain(items)
        domain_risks = aggregator.compute_domain_risk(items)
        top_entities_list = aggregator.top_entities(items, n=10)

        # 2. Graph reasoning
        reasoner = GraphReasoner(
            graph_engine=OntologyGraphEngine(self._neo4j),
            vector_store=self._vector,
        )
        tension_signals = await reasoner.analyse_entity_tensions(top_entities_list[:8])
        india_exposure = await reasoner.compute_india_exposure(tension_signals)

        # 3. Rule evaluation
        rule_engine = RuleEngine()
        rule_matches = rule_engine.evaluate(items, tension_signals)

        # 4. Scenario building
        builder = ScenarioBuilder(reasoner, rule_engine)
        hypothesis = (
            f"{tension_signals[0].source_entity} — {tension_signals[0].relation_type} — "
            f"{tension_signals[0].target_entity}"
            if tension_signals
            else "Global risk assessment"
        )
        tree = await builder.build_scenario_tree(hypothesis, items, tension_signals)
        scenario_branches = tree.get("branches", [])

        # 5. Redis context
        risk_raw = await self.redis.get("goe:india_risk_score_full")
        risk = (
            json.loads(risk_raw)
            if risk_raw
            else {"score": int(india_exposure), "color": "amber", "label": "MODERATE"}
        )
        market_raw = await self.redis.get("goe:market_snapshot")
        market = json.loads(market_raw) if market_raw else {}

        # 6. Entity counts
        entity_counts: dict[str, int] = {}
        for item in items:
            for ent in item.entities or []:
                name = ent.get("text", "") if isinstance(ent, dict) else str(ent)
                if name:
                    entity_counts[name] = entity_counts.get(name, 0) + 1

        # 7. Assemble brief
        ctx = BriefContext(
            date_str=today,
            india_risk=risk,
            market=market,
            domain_groups=grouped,
            domain_risks=domain_risks,
            tension_signals=tension_signals,
            top_entities=top_entities_list,
            entity_counts=entity_counts,
            scenario_branches=scenario_branches,
            total_signal_count=len(items),
            india_exposure=india_exposure,
        )
        assembler = BriefAssembler()
        content, sections = assembler.assemble(ctx)

        # 8. Cache in Redis
        try:
            await self.redis.setex(
                f"goe:antigravity:domain_risks:{today}",
                3600,
                json.dumps(domain_risks),
            )
            await self.redis.setex(
                f"goe:antigravity:tensions:{today}",
                1800,
                json.dumps([
                    {
                        "source": t.source_entity,
                        "target": t.target_entity,
                        "type": t.relation_type,
                        "score": t.tension_score,
                    }
                    for t in tension_signals[:20]
                ]),
            )
        except Exception as cache_exc:
            logger.warning("Redis caching failed: %s", cache_exc)

        return content, sections, risk["score"]

    async def _generate_llm(self, db, today: str) -> tuple[str, dict, int]:
        """Original LLM-based brief generation (extracted from old generate method)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        query = (
            select(IntelligenceItem)
            .where(IntelligenceItem.published_at >= cutoff)
            .order_by(desc(IntelligenceItem.severity))
            .limit(50)
        )
        result = await db.execute(query)
        items = result.scalars().all()

        context_lines = [
            f"[{item.source_name} | {item.domain.upper()} | Sev:{item.severity} | India:{item.india_score}] {item.title}"
            for item in items[:25]
        ]

        risk_raw = await self.redis.get("goe:india_risk_score_full")
        risk = json.loads(risk_raw) if risk_raw else {"score": 50, "color": "amber", "label": "MODERATE"}
        market_raw = await self.redis.get("goe:market_snapshot")
        market = json.loads(market_raw) if market_raw else {}

        prompt = f"""Generate the GOE Daily Strategic Intelligence Brief for {today}.

INDIA RISK SCORE: {risk['score']}/100 ({risk.get('label', 'MODERATE')})
MARKET CONTEXT: USD/INR {market.get('forex', {}).get('INR', market.get('USDINR', 'N/A'))} | Signals today: {len(items)}

TODAY'S TOP INTELLIGENCE SIGNALS:
{chr(10).join(context_lines) or 'No signals available.'}

Write the complete brief in this EXACT format:

--- GOE DAILY STRATEGIC INTELLIGENCE BRIEF ---
Date: {datetime.now(timezone.utc).strftime('%A, %d %B %Y')}
Classification: FOR AUTHORISED PERSONNEL ONLY
India Risk Score: {risk['score']}/100 - {risk.get('label', 'MODERATE')}

EXECUTIVE SUMMARY
[3-4 sentences covering the most critical developments globally and for India today]

INDIA STRATEGIC UPDATE
- Risk trend: [direction and reason]
- Priority action item: [one specific thing]
- Key opportunity: [one specific opportunity]

[GEOPOLITICS]
[Top geopolitical development - 2-3 paragraphs, India angle]

[ECONOMICS]
[Top economic development - 2-3 paragraphs]

[DEFENSE]
[Top defense/security development - 2-3 paragraphs]

[TECHNOLOGY]
[Top technology development - 2-3 paragraphs]

[CLIMATE]
[Top climate/disaster development - 2-3 paragraphs]

THREAT MATRIX
Domain | Risk Level | India Impact | Trend
Geopolitics | HIGH/MED/LOW | X/100 | UP/DOWN/FLAT
Economics   | ...
Defense     | ...
Technology  | ...
Climate     | ...

STRATEGIC PRIORITIES FOR INDIA (Next 7 days)
1. [Specific, actionable, measurable]
2. [Specific, actionable, measurable]
3. [Specific, actionable, measurable]

ENTITIES TO WATCH
- [Entity]: [why, what to monitor]
- [Entity]: [why, what to monitor]
- [Entity]: [why, what to monitor]

--- END OF BRIEF ---
Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | GOE v4.0"""

        content = await self.llm.complete(prompt, system=BRIEF_SYSTEM, max_tokens=3000)
        content = content or "Brief generation failed."
        return content, {}, risk["score"]