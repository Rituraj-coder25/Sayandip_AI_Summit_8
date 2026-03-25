"""
GOE Intelligence Engine - the central AI processing pipeline.
Every raw signal dict from every connector passes through this.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.intelligence import IntelligenceItem
from ...models.signal import RawSignal
from ..ontology.graph_engine import OntologyGraphEngine
from .bharatiya import is_bharatiya, translate_and_enrich
from .brief_generator import BriefGenerator, LLMClient
from .classifier import SignalClassifier
from .india_scorer import IndiaRelevanceScorer
from .ner import SpacyNERExtractor
from .vector_store import GOEVectorStore

logger = logging.getLogger("goe.engine")


class GOEIntelligenceEngine:
    def __init__(
        self,
        neo4j_driver,
        vector_store: GOEVectorStore,
        redis_client,
        db_factory,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.1:8b",
        anthropic_key: str | None = None,
        llm: LLMClient | None = None,
    ):
        self._llm = llm or LLMClient(ollama_url, ollama_model, anthropic_key)
        self._ner = SpacyNERExtractor()
        self._clf = SignalClassifier(self._llm)
        self._scorer = IndiaRelevanceScorer()
        self._vector = vector_store
        self._redis = redis_client
        self._db_factory = db_factory
        self._graph = OntologyGraphEngine(neo4j_driver)
        self._briefs = BriefGenerator(self._llm, vector_store)

    async def startup(self):
        await self._llm.detect_mode()
        logger.info("Intelligence engine ready")

    async def process_signal(self, raw_signal: dict, db: AsyncSession) -> IntelligenceItem | None:
        source_name = raw_signal.get("source_name") or raw_signal.get("source") or "unknown"
        raw_signal["source_name"] = source_name
        raw_signal.setdefault("source", source_name)

        combined_text = f"{raw_signal.get('title', '')} {raw_signal.get('summary', '')}".strip()
        if is_bharatiya(combined_text):
            raw_signal = await translate_and_enrich(raw_signal, self._llm)
            combined_text = f"{raw_signal.get('title', '')} {raw_signal.get('summary', '')}".strip()

        if len(combined_text) < 20:
            return None

        signal_id = raw_signal.get("id") or str(uuid.uuid4())
        existing = await db.execute(select(IntelligenceItem).where(IntelligenceItem.id == signal_id))
        if existing.scalar_one_or_none() is not None:
            return None

        if self._vector.is_duplicate(combined_text, threshold=0.97):
            logger.debug("Duplicate skipped: %s", combined_text[:50])
            return None

        entities = self._ner.extract(combined_text)
        domain = raw_signal.get("domain") or await self._clf.classify_domain(combined_text)
        severity = int(raw_signal.get("severity") or await self._clf.score_severity(combined_text, domain, entities))
        india_score = int(
            raw_signal.get("india_score")
            or self._scorer.score(
                combined_text,
                entities,
                lat=raw_signal.get("latitude"),
                lon=raw_signal.get("longitude"),
            )
        )
        relations = self._ner.extract_relations(combined_text, entities)

        asyncio.create_task(self._graph.upsert_from_signal(entities, relations, raw_signal))

        self._vector.upsert(
            signal_id,
            combined_text,
            {
                "domain": domain,
                "severity": severity,
                "india_score": india_score,
                "source": source_name,
                "published_at": raw_signal.get("published_at", ""),
            },
        )

        ai_brief = await self._briefs.generate(combined_text, entities, domain, severity, india_score)
        published_at = self._parse_dt(raw_signal.get("published_at"))

        item = IntelligenceItem(
            id=signal_id,
            source_name=source_name,
            title=raw_signal.get("title", "")[:500],
            summary=raw_signal.get("summary", "")[:1000],
            ai_brief=ai_brief,
            domain=domain,
            severity=severity,
            india_score=india_score,
            entities=entities,
            latitude=raw_signal.get("latitude"),
            longitude=raw_signal.get("longitude"),
            source_url=raw_signal.get("source_url") or raw_signal.get("url"),
            published_at=published_at,
            vector_id=signal_id,
            raw_text=combined_text[:2000],
            tags=raw_signal.get("tags") or [],
            translated=raw_signal.get("translated", False),
            original_lang=raw_signal.get("original_lang"),
        )
        raw = RawSignal(
            id=f"raw_{signal_id}",
            source_name=source_name,
            raw_data=raw_signal,
            payload=raw_signal,
            external_id=raw_signal.get("external_id") or raw_signal.get("id"),
            raw_text=combined_text[:4000],
            processed=True,
            status="PROCESSED",
            published_at=published_at,
        )

        db.add(raw)
        db.add(item)
        await db.flush()

        await self._redis.setex(f"goe:signal:{signal_id}", 3600, json.dumps(item.to_dict()))
        await self._redis.incr("goe:stats:signals_today")
        await self._redis.incr(f"goe:stats:domain:{domain}")
        if india_score >= 70:
            await self._redis.incr("goe:stats:india_signals_today")

        return item

    @staticmethod
    def _parse_dt(value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)