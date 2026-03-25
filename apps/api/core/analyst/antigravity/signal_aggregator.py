"""
SignalAggregator — fetches and groups IntelligenceItems from Postgres
by domain and severity. No LLM calls.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from ....models.intelligence import IntelligenceItem
from ...intelligence.classifier import DOMAINS

logger = logging.getLogger("goe.antigravity.signal_aggregator")


class SignalAggregator:
    def __init__(self, db_session_factory):
        self._db_factory = db_session_factory

    async def fetch_recent(self, hours: int = 24, limit: int = 100) -> list[IntelligenceItem]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = (
            select(IntelligenceItem)
            .where(IntelligenceItem.published_at >= cutoff)
            .order_by(desc(IntelligenceItem.severity))
            .limit(limit)
        )
        async with self._db_factory() as session:
            result = await session.execute(query)
            return list(result.scalars().all())

    def group_by_domain(self, items: list[IntelligenceItem]) -> dict[str, list[IntelligenceItem]]:
        groups: dict[str, list[IntelligenceItem]] = {d: [] for d in DOMAINS}
        for item in items:
            domain = item.domain if item.domain in DOMAINS else "geopolitics"
            groups[domain].append(item)
        # Sort each group by severity descending
        for domain in groups:
            groups[domain].sort(key=lambda x: (x.severity or 0), reverse=True)
        return groups

    def compute_domain_risk(self, items: list[IntelligenceItem]) -> dict[str, int]:
        grouped = self.group_by_domain(items)
        risks: dict[str, int] = {}
        for domain in DOMAINS:
            domain_items = grouped.get(domain, [])
            if not domain_items:
                risks[domain] = 0
                continue
            severities = [item.severity or 0 for item in domain_items]
            india_scores = [item.india_score or 0 for item in domain_items]
            domain_risk = min(
                100,
                int(
                    statistics.mean(severities) * 0.6
                    + statistics.mean(india_scores) * 0.4
                ),
            )
            risks[domain] = domain_risk
        return risks

    def top_entities(self, items: list[IntelligenceItem], n: int = 10) -> list[str]:
        counter: Counter = Counter()
        for item in items:
            for ent in (item.entities or []):
                text = ent.get("text", "") if isinstance(ent, dict) else str(ent)
                if len(text) >= 3:
                    counter[text] += 1
        return [entity for entity, _ in counter.most_common(n)]

    def top_items_per_domain(
        self, grouped: dict[str, list[IntelligenceItem]], n: int = 3
    ) -> dict[str, list[IntelligenceItem]]:
        return {domain: items[:n] for domain, items in grouped.items()}
