import json

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/sources")
async def get_sources_overview(request: Request):
    return await _source_health_payload(request)


@router.get("/sources/health")
async def get_source_health(request: Request):
    return await _source_health_payload(request)


@router.post("/run-connector")
async def run_connector_by_body(request: Request, name: str):
    scheduler = request.app.state.scheduler
    await scheduler.force_run(name)
    return {"status": "triggered", "connector": name}


@router.post("/connectors/{name}/run")
async def force_run_connector(request: Request, name: str):
    scheduler = request.app.state.scheduler
    await scheduler.force_run(name)
    return {"status": "triggered", "connector": name}


@router.get("/stats")
async def get_system_stats(request: Request):
    redis = request.app.state.redis
    vector = request.app.state.vector

    signals_today = await redis.get("goe:stats:signals_today") or 0
    india_risk = await redis.get("goe:india_risk_score") or 0
    return {
        "signals_today": int(signals_today),
        "vectors_stored": vector.count(),
        "india_risk_score": int(india_risk),
        "connectors": len(request.app.state.scheduler.connectors),
    }


async def _source_health_payload(request: Request):
    redis = request.app.state.redis
    connector_names = list(request.app.state.scheduler.connectors.keys())

    sources = []
    for name in connector_names:
        health_raw = await redis.hgetall(f"goe:source_health:{name}")
        last_fetch = await redis.get(f"goe:last_fetch:{name}")
        sources.append(
            {
                "name": name,
                "status": health_raw.get("status", "unknown"),
                "last_success": health_raw.get("last_success"),
                "last_error": health_raw.get("last_error"),
                "items_count": int(health_raw.get("items_count", "0") or 0),
                "last_fetch_ts": float(last_fetch) if last_fetch else None,
            }
        )

    return {"sources": sources}


# ── Agent Endpoints ──────────────────────────────────────────────────────

@router.get("/agents/health")
async def get_agent_health(request: Request):
    """
    GET /api/v1/admin/agents/health
    Returns health status of all scraper agents.
    """
    redis  = request.app.state.redis
    agents = [
        "world_monitor_live",
        "playwright_news_scraper",
        "ai_director",
    ]
    results = []
    for name in agents:
        health   = await redis.hgetall(f"goe:agent_health:{name}")
        last_fetch_raw = await redis.get(f"goe:last_fetch:agent:{name}")
        results.append({
            "name":       name,
            "status":     health.get("status", "unknown"),
            "last_success": health.get("last_success"),
            "last_error":  health.get("last_error"),
            "items_count": health.get("items_count", "0"),
            "latency_ms":  health.get("latency_ms"),
            "ws_status":   health.get("ws_status", "not_applicable"),
            "last_fetch":  float(last_fetch_raw) if last_fetch_raw else None,
        })
    directive_raw = await redis.get("goe:agent:director_directive")
    directive     = json.loads(directive_raw) if directive_raw else None
    return {"agents": results, "director_directive": directive}


@router.post("/agents/{name}/run")
async def force_run_agent(name: str, request: Request):
    """
    POST /api/v1/admin/agents/{name}/run
    Force-run a specific agent immediately.
    """
    redis     = request.app.state.redis
    scheduler = request.app.state.scheduler

    await redis.delete(f"goe:last_fetch:agent:{name}")
    await redis.delete(f"goe:cache:agent:{name}")

    agent = next((a for a in scheduler.agents if a.AGENT_NAME == name), None)
    if not agent:
        return {"error": f"Agent '{name}' not found"}

    await scheduler._run_agent(agent)
    return {"status": "triggered", "agent": name}


@router.get("/agents/director/directive")
async def get_director_directive(request: Request):
    """Returns the AI Director's current scraping directive."""
    redis = request.app.state.redis
    raw   = await redis.get("goe:agent:director_directive")
    if not raw:
        return {"directive": None, "message": "No directive yet — director runs every 30 min"}
    return {"directive": json.loads(raw)}