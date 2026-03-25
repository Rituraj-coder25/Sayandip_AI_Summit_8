"""
GOE-1 - the strategic AI analyst.
Wraps every user query in live context before calling the LLM.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("goe.analyst")

GOE_SYSTEM_PROMPT = """You are GOE-1 - Global Ontology Engine Strategic Intelligence Analyst.
You serve the Government of India and authorised analysts.

STRICT RULES:
1. Every claim must be traceable to the CONTEXT BLOCK below.
2. If the context lacks data to answer, say: \"GOE data insufficient - recommend querying [source].\"
3. Always cite which source your information came from.
4. Always include data freshness: [LIVE] [1H] [6H] [24H] [HISTORICAL]
5. For India-specific assessments, always lead with India Impact Score (0-100).
6. For severity >= 70, always end with a STRATEGIC RECOMMENDATION.
7. Clearly mark: CONFIRMED (from live data) | ASSESSED (inferred) | HISTORICAL

OUTPUT FORMAT:
## [DOMAIN] - [HEADLINE]
**India Impact: X/100** | Confidence: HIGH/MEDIUM/LOW | Freshness: [tag]
**Situation**: [factual summary]
**Key Actors**: [list]
**India Exposure**: [specific mechanism]
**Trend**: ESCALATING | STABLE | DE-ESCALATING
**Sources**: [actual source names from context]
**Strategic Recommendation**: [only for severity >60]"""


class GOEAnalyst:
    def __init__(self, vector_store, neo4j_driver, redis_client, intelligence_engine):
        self._vector = vector_store
        self._neo4j = neo4j_driver
        self._redis = redis_client
        self._llm = intelligence_engine._llm

    async def query(self, question: str, user_role: str, conversation_history: list[dict]) -> dict:
        context = await self._build_context(question)
        hits = self._vector.query(question, n_results=10)
        signal_lines = [
            (
                f"[{hit['metadata'].get('source', '')} | {hit['metadata'].get('domain', '').upper()} | "
                f"Severity:{hit['metadata'].get('severity', 0)} | India:{hit['metadata'].get('india_score', 0)}] "
                f"{hit['document'][:200]}"
            )
            for hit in hits
        ]
        graph_ctx = await self._graph_context(question)
        history_block = json.dumps(conversation_history[-6:], ensure_ascii=False) if conversation_history else "[]"

        full_prompt = f"""{context}

TOP RELEVANT INTELLIGENCE SIGNALS:
{chr(10).join(signal_lines) or 'No matching signals in current corpus.'}

KNOWLEDGE GRAPH CONTEXT:
{graph_ctx or 'No entity relationships found.'}

CONVERSATION HISTORY:
{history_block}

---
QUESTION: {question}"""

        prefer_fast = user_role not in ("SENIOR_ANALYST", "DIRECTOR")
        response = await self._llm.complete(full_prompt, system=GOE_SYSTEM_PROMPT, max_tokens=2000, prefer_fast=prefer_fast)

        return {
            "response": response or "GOE-1 temporarily unavailable.",
            "sources_used": list({hit["metadata"].get("source", "") for hit in hits}),
            "context_signals": len(hits),
            "model_mode": self._llm._mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _build_context(self, question: str) -> str:
        lines = [f"=== GOE LIVE CONTEXT - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ==="]

        risk_raw = await self._redis.get("goe:india_risk_score_full")
        if risk_raw:
            risk = json.loads(risk_raw)
            lines.append(f"INDIA RISK SCORE: {risk['score']}/100 ({risk['color'].upper()})")

        market_raw = await self._redis.get("goe:market_snapshot")
        if market_raw:
            market = json.loads(market_raw)
            inr = None
            if isinstance(market.get("forex"), dict):
                inr = market.get("forex", {}).get("INR")
            elif market.get("USDINR") is not None:
                inr = market.get("USDINR")
            if inr is not None:
                lines.append(f"USD/INR: {inr} [LIVE]")
            btc = None
            if isinstance(market.get("crypto"), dict):
                btc = market.get("crypto", {}).get("bitcoin")
            if isinstance(btc, dict):
                lines.append(f"BTC: ${btc.get('usd', 0):,.0f} ({btc.get('usd_24h_change', 0):+.1f}% 24h) [LIVE]")

        usgs_raw = await self._redis.get("goe:cache:usgs_earthquakes")
        if usgs_raw:
            quakes = json.loads(usgs_raw)
            if quakes:
                top = max(quakes, key=lambda item: item.get("severity", 0))
                lines.append(f"MAX SEISMIC TODAY: {top.get('title', '')[:70]} [LIVE]")

        processed = await self._redis.get("goe:stats:signals_today")
        if processed:
            lines.append(f"SIGNALS PROCESSED TODAY: {processed}")

        lines.append("=== END CONTEXT ===")
        return "\n".join(lines)

    async def _graph_context(self, question: str) -> str:
        keywords = ["india", "china", "pakistan", "usa", "russia", "iran", "ukraine", "taiwan", "israel", "saudi", "nato", "quad", "brics"]
        mentioned = [keyword.title() for keyword in keywords if keyword in question.lower()]
        if not mentioned:
            return ""

        try:
            async with self._neo4j.session() as session:
                result = await session.run(
                    """
                    MATCH (n:Nation)-[r]-(m)
                    WHERE n.name IN $nations
                    RETURN n.name as nation, type(r) as rel, m.name as partner,
                           r.strength_score as strength, r.mention_count as mentions
                    ORDER BY r.strength_score DESC
                    LIMIT 15
                    """,
                    nations=mentioned[:3],
                )
                rows = [record.data() async for record in result]

            return "\n".join(
                [
                    f"{row['nation']} -[{row['rel']}]> {row['partner']}"
                    + (
                        f" (strength:{float(row.get('strength') or 0):.2f}, mentions:{int(row.get('mentions') or 0)})"
                        if row.get("strength") is not None
                        else ""
                    )
                    for row in rows
                ]
            )
        except Exception:
            return ""