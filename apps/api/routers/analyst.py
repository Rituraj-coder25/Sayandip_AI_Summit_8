from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..schemas.analyst import QueryRequest, ScenarioRequest

router = APIRouter()


class FeedbackRequest(BaseModel):
    response_id: str
    rating: int
    component: str = ""
    comment: str = ""


@router.post("/query")
async def analyst_query(req: QueryRequest, request: Request):
    from ..core.analyst.antigravity.query_engine import AntigravityQueryEngine

    try:
        from ..database import AsyncSessionLocal
    except Exception:
        AsyncSessionLocal = None

    engine = AntigravityQueryEngine(
        redis=getattr(request.app.state, "redis", None),
        vector_store=getattr(request.app.state, "vector", None),
        neo4j_driver=getattr(request.app.state, "neo4j", None),
        db_factory=AsyncSessionLocal,
        llm=getattr(getattr(request.app.state, "engine", None), "_llm", getattr(request.app.state, "llm", None)),
    )
    answer = await engine.answer(req.question, req.context)
    return {
        "answer": answer,
        "response": answer,
        "engine": "antigravity_v1",
        "question": req.question,
    }


@router.post("/scenario")
async def run_scenario(req: ScenarioRequest, request: Request):
    """
    Run a geopolitical scenario through GOE-1 ScenarioEngine (probability tree)
    AND optionally through the MiroFish swarm-intelligence plugin (agent simulation).

    If MIROFISH_ENABLED=true in config and the plugin is reachable, both engines
    run concurrently (asyncio.gather). The final response merges both results.
    If MiroFish is disabled or unavailable, only the GOE tree is returned with
    plugin_status: "disabled" or "unavailable".
    """
    import asyncio

    from ..core.analyst.scenario_engine import ScenarioEngine
    from ..database import AsyncSessionLocal

    # Build the GOE scenario engine
    engine = ScenarioEngine(
        llm=request.app.state.engine._llm,
        redis_client=request.app.state.redis,
        vector_store=request.app.state.vector,
        neo4j_driver=request.app.state.neo4j,
        db_factory=AsyncSessionLocal,
    )

    # Fetch RAG context signals for MiroFish seed enrichment
    context_signals = request.app.state.vector.query(req.hypothesis, n_results=5)

    # Run GOE tree + MiroFish simulation concurrently
    mirofish_plugin = request.app.state.mirofish

    # Determine whether swarm should run based on per-request override or global config
    swarm_enabled = req.use_swarm if req.use_swarm is not None else mirofish_plugin.config.get("enabled", False)

    async def run_mirofish():
        if not swarm_enabled:
            return {"plugin": "mirofish", "status": "disabled"}
        return await mirofish_plugin.run_simulation(req.hypothesis, context_signals)

    goe_task = engine.generate_scenario_tree(req.hypothesis, req.depth)
    mirofish_task = run_mirofish()

    tree, swarm_result = await asyncio.gather(goe_task, mirofish_task)

    # Merge MiroFish swarm findings into the GOE probability tree branches
    if swarm_result.get("status") == "success":
        tree = _merge_swarm_into_tree(tree, swarm_result)

    return {
        "tree": tree,
        "swarm_simulation": swarm_result,
        "plugin_status": swarm_result.get("status", "disabled"),
    }


def _merge_swarm_into_tree(tree: dict, swarm: dict) -> dict:
    """
    Enrich the GOE probability tree with MiroFish swarm intelligence data.
    This adds swarm-level validation and emergent insights to each branch.
    """
    # Attach swarm summary to the top-level tree
    tree["swarm_summary"] = swarm.get("swarm_summary", "")
    tree["swarm_key_findings"] = swarm.get("swarm_key_findings", [])
    tree["dominant_narrative"] = swarm.get("dominant_narrative", "")
    tree["dissenting_views"] = swarm.get("dissenting_views", [])

    # Match swarm predicted outcomes to GOE branches by label similarity
    swarm_outcomes = swarm.get("swarm_predicted_outcomes", [])
    branches = tree.get("branches", [])

    for i, branch in enumerate(branches):
        # Try to find a matching swarm outcome by index or label
        swarm_match = swarm_outcomes[i] if i < len(swarm_outcomes) else {}
        branch["swarm_probability"] = swarm_match.get("probability")
        branch["swarm_actor_consensus"] = swarm_match.get("actor_consensus", "")
        branch["swarm_validated"] = swarm_match.get("probability") is not None

    tree["swarm_simulation_stats"] = swarm.get("simulation_stats", {})
    return tree


@router.post("/daily-brief")
async def generate_daily_brief(request: Request):
    from ..core.analyst.daily_brief import DailyBriefGenerator
    from ..database import AsyncSessionLocal

    generator = DailyBriefGenerator(
        redis_client=request.app.state.redis,
        llm=request.app.state.engine._llm,
        neo4j_driver=request.app.state.neo4j,
        vector_store=request.app.state.vector,
        db_factory=AsyncSessionLocal,
    )
    async with AsyncSessionLocal() as db:
        brief = await generator.generate(db)
        await db.commit()
    return {"brief_id": brief.id, "content": brief.content, "date": brief.date}


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request):
    import json
    from datetime import datetime, timezone

    redis = request.app.state.redis
    feedback = {
        "response_id": req.response_id,
        "rating": req.rating,
        "component": req.component,
        "comment": req.comment[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await redis.lpush("goe:analyst_feedback", json.dumps(feedback))
    await redis.ltrim("goe:analyst_feedback", 0, 999)

    count = await redis.llen("goe:analyst_feedback")
    if count % 50 == 0:
        from ..core.india.risk_score import analyst_feedback_reweight

        await analyst_feedback_reweight(redis)

    if req.rating == 1:
        await redis.incr("goe:feedback:accurate")
    elif req.rating == -1:
        await redis.incr("goe:feedback:inaccurate")

    return {"status": "recorded", "total_ratings": count}
