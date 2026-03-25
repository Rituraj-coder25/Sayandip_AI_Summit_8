import logging
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import AsyncGraphDatabase

from .config import settings
from .core.alerts.alert_engine import AlertEngine
from .core.analyst.goe_analyst import GOEAnalyst
from .core.intelligence.brief_generator import LLMClient
from .core.intelligence.engine import GOEIntelligenceEngine
from .core.intelligence.vector_store import GOEVectorStore
from .database import AsyncSessionLocal, init_db
from .ingestion.scheduler import GOEScheduler
from .models import Alert, DailyBrief, IntelligenceItem, RawSignal, Scenario, User
from .routers import admin, alerts as alerts_router, analyst, india, intelligence as intelligence_router, ontology, reports, signals

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO), format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("goe")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GOE Engine starting...")

    http = httpx.AsyncClient(headers={"User-Agent": "GOE-Intelligence/4.0"}, follow_redirects=True, timeout=httpx.Timeout(30.0))
    redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis.ping()
    logger.info("[ok] Redis")

    neo4j = AsyncGraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
    await neo4j.verify_connectivity()
    logger.info("[ok] Neo4j")

    await init_db()
    logger.info("[ok] PostgreSQL")

    vector = GOEVectorStore(settings.CHROMADB_DIR)
    logger.info("[ok] ChromaDB (%s vectors)", vector.count())

    # ── MiroFish Plugin ──
    from .core.analyst.mirofish_plugin import MiroFishPlugin

    mirofish = MiroFishPlugin(config={
        "mirofish_url": settings.MIROFISH_URL,
        "mirofish_api_key": settings.MIROFISH_API_KEY,
        "num_agents": settings.MIROFISH_NUM_AGENTS,
        "simulation_rounds": settings.MIROFISH_SIMULATION_ROUNDS,
        "timeout_seconds": settings.MIROFISH_TIMEOUT_SECONDS,
        "enabled": settings.MIROFISH_ENABLED,
    })
    if settings.MIROFISH_ENABLED:
        available = await mirofish.is_available()
        logger.info("MiroFish plugin: %s", "ONLINE" if available else "OFFLINE (will skip)")
    else:
        logger.info("MiroFish plugin: DISABLED (set MIROFISH_ENABLED=true to activate)")

    llm = LLMClient(settings.OLLAMA_URL, settings.OLLAMA_MODEL, settings.ANTHROPIC_API_KEY)
    await llm.detect_mode()
    logger.info("[ok] LLM (%s)", llm._mode)

    engine = GOEIntelligenceEngine(
        neo4j_driver=neo4j,
        vector_store=vector,
        redis_client=redis,
        db_factory=AsyncSessionLocal,
        ollama_url=settings.OLLAMA_URL,
        ollama_model=settings.OLLAMA_MODEL,
        anthropic_key=settings.ANTHROPIC_API_KEY,
        llm=llm,
    )
    logger.info("[ok] Intelligence engine")

    alert_engine = AlertEngine(redis)
    analyst_service = GOEAnalyst(vector_store=vector, neo4j_driver=neo4j, redis_client=redis, intelligence_engine=engine)

    scheduler = GOEScheduler(
        redis_client=redis,
        http_client=http,
        db_factory=AsyncSessionLocal,
        intelligence_engine=engine,
        alert_engine=alert_engine,
    )
    scheduler.start()
    logger.info("[ok] Scheduler (%s connectors + %s agents)", len(scheduler.connectors), len(scheduler.agents))

    # Inject LLM into AIDirectorAgent
    from .ingestion.agents.ai_director_agent import AIDirectorAgent
    for agent in scheduler.agents:
        if isinstance(agent, AIDirectorAgent):
            agent._llm = llm

    # Start WebSocket background tasks
    await scheduler.start_agent_background_tasks()
    logger.info("[ok] Agent WebSocket listeners started")

    import asyncio

    async def _compute_risk():
        from .core.india.risk_score import compute_india_risk_score

        async with AsyncSessionLocal() as db:
            await compute_india_risk_score(db, redis)

    asyncio.create_task(_compute_risk())

    app.state.redis = redis
    app.state.neo4j = neo4j
    app.state.vector = vector
    app.state.engine = engine
    app.state.analyst = analyst_service
    app.state.scheduler = scheduler
    app.state.llm = llm
    app.state.http = http
    app.state.mirofish = mirofish

    logger.info("GOE Engine fully operational")
    try:
        yield
    finally:
        scheduler.stop()
        await llm.close()
        await http.aclose()
        await redis.aclose()
        await neo4j.close()
        logger.info("GOE shutdown complete")


app = FastAPI(title="GOE", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router, prefix="/api/v1/signals")
app.include_router(intelligence_router.router, prefix="/api/v1/intelligence")
app.include_router(analyst.router, prefix="/api/v1/analyst")
app.include_router(india.router, prefix="/api/v1/india")
app.include_router(ontology.router, prefix="/api/v1/ontology")
app.include_router(reports.router, prefix="/api/v1/reports")
app.include_router(alerts_router.router, prefix="/api/v1/alerts")
app.include_router(admin.router, prefix="/api/v1/admin")


@app.get("/health")
async def health():
    return {
        "status": "operational",
        "version": "4.0.0",
        "llm_mode": app.state.llm._mode if hasattr(app.state, "llm") else "unknown",
        "connectors": len(app.state.scheduler.connectors) if hasattr(app.state, "scheduler") else 0,
    }