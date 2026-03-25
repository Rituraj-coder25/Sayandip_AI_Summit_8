# MiroFish Plugin Integration Prompt — GOE Scenarios Feature

**Project:** Sayandip AI Summit / Global Ontology Engine (GOE-1)  
**Target Feature:** `POST /analyst/scenario` → `ScenarioEngine`  
**Plugin Source:** https://github.com/666ghj/MiroFish  
**Integration Goal:** When a user submits a geopolitical scenario/hypothesis, the GOE Scenarios feature should invoke MiroFish as a swarm-intelligence simulation layer that spawns thousands of autonomous AI agents inside a parallel digital world, allowing emergent multi-agent behaviour to enrich and validate the probability tree returned by the existing `ScenarioEngine`.

---

## 1. Context & Architecture Overview

### Existing GOE Scenarios Pipeline (what you already have)

```
POST /analyst/scenario
  ↓
ScenarioRequest (hypothesis: str, depth: int)
  ↓
ScenarioEngine.generate_scenario_tree()
  → vector_store.query()        # RAG context from ChromaDB
  → self._llm.complete(prompt)  # Ollama / Anthropic LLM
  ↓
Returns: JSON probability tree (branches A/B/C, india_impact_score, etc.)
```

The existing `ScenarioEngine` is a **single-agent, single-pass LLM call**. It is good at structural reasoning but has no emergent social dynamics, no agent-level divergence, and no simulation of how thousands of individual actors (policymakers, market participants, state actors, media) would actually behave under the scenario.

### What MiroFish Adds

MiroFish is a **swarm-intelligence simulation engine** built on the OASIS (Open Agent Social Interaction Simulations) framework by CAMEL-AI. When given seed material (a scenario description), it:

1. Extracts entities and relationships → builds a knowledge graph of actors
2. Generates thousands of autonomous agents, each with a unique personality, memory, and role
3. Runs multi-round social simulations where agents interact, react, post, counter-post, follow, and evolve
4. Produces a `ReportAgent`-generated synthesis with emergent insights not achievable by a single LLM call

The integration adds a **MiroFish Plugin** that runs in parallel or sequentially alongside the existing `ScenarioEngine`, then merges both outputs into an enriched, swarm-validated scenario tree.

---

## 2. Full Integration Prompt

Paste the following as the developer/system prompt when implementing this integration. It is self-contained and instructs the implementing agent on exactly what to build.

---

```
You are implementing a MiroFish plugin for the GOE-1 (Global Ontology Engine) Scenarios feature.
The GOE-1 codebase is a Python/FastAPI backend located at apps/api/.
You have read and understood the following files:
  - apps/api/core/analyst/scenario_engine.py
  - apps/api/routers/analyst.py
  - apps/api/schemas/analyst.py
  - apps/api/config.py
  - apps/api/core/intelligence/engine.py

MiroFish repository: https://github.com/666ghj/MiroFish
MiroFish is a multi-agent swarm-intelligence simulation engine powered by OASIS/CAMEL-AI.
Its backend is a Flask application. Its LLM layer accepts any OpenAI-SDK-compatible API.
It takes "seed material" (text describing a scenario) and a prediction question, then simulates
thousands of agents with independent personalities and long-term memory to produce a prediction
report via a ReportAgent.

YOUR TASK: Implement a MiroFish plugin for the GOE Scenarios feature following ALL of the
specifications below exactly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION A — NEW FILES TO CREATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create the file:
  apps/api/core/analyst/mirofish_plugin.py

This module must contain a single class `MiroFishPlugin` with the following interface:

  class MiroFishPlugin:
      def __init__(self, config: dict): ...
      async def run_simulation(self, hypothesis: str, context_signals: list[dict]) -> dict: ...
      async def is_available(self) -> bool: ...

### MiroFishPlugin.__init__

Accept a `config` dict with these keys:
  - mirofish_url: str          # Base URL of MiroFish Flask backend, e.g. "http://localhost:5001"
  - mirofish_api_key: str      # Optional bearer token for MiroFish if deployed with auth
  - num_agents: int            # Number of agents to spawn (default 500, max 5000 for performance)
  - simulation_rounds: int     # How many interaction rounds (default 10)
  - timeout_seconds: int       # HTTP timeout (default 120)
  - enabled: bool              # Feature flag — if False, skip silently

Store all values as instance attributes. Create an aiohttp.ClientSession lazily.

### MiroFishPlugin.is_available

Send a GET request to {mirofish_url}/health or {mirofish_url}/api/status.
Return True if HTTP 200 is received within 5 seconds. Return False otherwise (never raise).
Log a WARNING if unavailable.

### MiroFishPlugin.run_simulation

This is the core method. It must:

STEP 1 — BUILD SEED MATERIAL
Construct a "seed" document from:
  - The raw `hypothesis` string (the geopolitical scenario)
  - Up to 5 items from `context_signals` (these come from GOE's ChromaDB vector store)
Format the seed as a structured plaintext document:

  === GOE GEOPOLITICAL SCENARIO SEED ===
  SCENARIO: {hypothesis}
  DATE: {current UTC datetime}
  
  RELEVANT INTELLIGENCE SIGNALS:
  {for each signal: "- [SOURCE | DOMAIN | SEVERITY:{n}] {document_text[:200]}"}
  
  PREDICTION QUESTION:
  "Given this scenario, simulate how key actors (governments, military, markets, media,
   civilian populations) will respond over the next 72 hours to 3 months. Focus on
   India's geopolitical exposure."

STEP 2 — SUBMIT SIMULATION JOB
POST to {mirofish_url}/api/simulate with JSON body:
  {
    "seed_material": "<seed from step 1>",
    "prediction_question": "...",    // same as above
    "num_agents": self.num_agents,
    "rounds": self.simulation_rounds,
    "agent_roles": [
      "Indian policy analyst",
      "Chinese military strategist",
      "US State Department official",
      "Pakistani ISI analyst",
      "Financial market trader",
      "International journalist",
      "UN humanitarian officer",
      "Iranian foreign ministry official",
      "Indian defence minister",
      "Central bank governor"
    ],
    "output_format": "json"
  }

If the endpoint returns 202 (Accepted) with a job_id, poll
{mirofish_url}/api/simulate/{job_id}/status every 10 seconds until status == "complete"
or timeout is reached.

If the endpoint returns 200 with immediate results, use those directly.

STEP 3 — PARSE MIROFISH OUTPUT
MiroFish returns a report from its ReportAgent. Parse the response body.
Expected structure (handle gracefully if fields are missing):
  {
    "report": { "summary": str, "key_findings": list[str], "predicted_outcomes": list[dict] },
    "agent_consensus": { "dominant_narrative": str, "dissenting_views": list[str] },
    "simulation_stats": { "rounds_completed": int, "agents_active": int },
    "raw_interactions_sample": list[dict]   // sample of agent messages
  }

STEP 4 — RETURN STRUCTURED ENRICHMENT DICT
Always return a dict with this schema regardless of success/failure:
  {
    "plugin": "mirofish",
    "status": "success" | "timeout" | "unavailable" | "error",
    "swarm_summary": str,          // 2-3 sentence synthesis
    "swarm_key_findings": list[str],  // up to 5 bullet points from simulation
    "swarm_predicted_outcomes": list[dict],  // [{label, probability, actor_consensus}]
    "dominant_narrative": str,     // what most agents converged on
    "dissenting_views": list[str], // minority-view agents' positions
    "simulation_stats": dict,      // rounds, agents, time
    "raw_sample": list[dict],      // first 3 agent interactions for transparency
    "error": str | None            // error message if status != "success"
  }

On any exception, log the error and return the dict with status="error", error=str(e),
and empty/null values for all other fields. NEVER let this method raise.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION B — MODIFY: apps/api/config.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Add the following fields to the Settings class (pydantic-settings BaseSettings):

  # ── MiroFish Plugin ──
  MIROFISH_ENABLED: bool = False
  MIROFISH_URL: str = "http://localhost:5001"
  MIROFISH_API_KEY: Optional[str] = None
  MIROFISH_NUM_AGENTS: int = 500
  MIROFISH_SIMULATION_ROUNDS: int = 10
  MIROFISH_TIMEOUT_SECONDS: int = 120

These must be readable from the .env file (already handled by pydantic-settings).
Add corresponding entries to the .env.example file:

  # ── MiroFish Swarm Intelligence Plugin ──
  MIROFISH_ENABLED=false
  MIROFISH_URL=http://localhost:5001
  MIROFISH_API_KEY=          # optional bearer token
  MIROFISH_NUM_AGENTS=500
  MIROFISH_SIMULATION_ROUNDS=10
  MIROFISH_TIMEOUT_SECONDS=120

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION C — MODIFY: apps/api/main.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

In the application startup lifespan (the @asynccontextmanager lifespan function), after
app.state.vector is initialised, add:

  from .core.analyst.mirofish_plugin import MiroFishPlugin
  from .config import get_settings

  settings = get_settings()
  app.state.mirofish = MiroFishPlugin(config={
      "mirofish_url": settings.MIROFISH_URL,
      "mirofish_api_key": settings.MIROFISH_API_KEY,
      "num_agents": settings.MIROFISH_NUM_AGENTS,
      "simulation_rounds": settings.MIROFISH_SIMULATION_ROUNDS,
      "timeout_seconds": settings.MIROFISH_TIMEOUT_SECONDS,
      "enabled": settings.MIROFISH_ENABLED,
  })

  if settings.MIROFISH_ENABLED:
      available = await app.state.mirofish.is_available()
      logger.info(f"MiroFish plugin: {'ONLINE' if available else 'OFFLINE (will skip)'}")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION D — MODIFY: apps/api/routers/analyst.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Replace the existing `run_scenario` endpoint with this new version:

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

      # Build the GOE scenario engine
      engine = ScenarioEngine(
          llm=request.app.state.engine._llm,
          redis_client=request.app.state.redis,
          vector_store=request.app.state.vector,
      )

      # Fetch RAG context signals for MiroFish seed enrichment
      context_signals = request.app.state.vector.query(req.hypothesis, n_results=5)

      # Run GOE tree + MiroFish simulation concurrently
      mirofish_plugin = request.app.state.mirofish

      async def run_mirofish():
          if not mirofish_plugin.config["enabled"]:
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION E — MODIFY: apps/api/schemas/analyst.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Update ScenarioRequest to add an optional override flag:

  class ScenarioRequest(BaseModel):
      hypothesis: str
      depth: int = 3
      use_swarm: Optional[bool] = None  
      # None = use global MIROFISH_ENABLED setting
      # True = force enable for this request (requires MIROFISH_URL accessible)
      # False = skip swarm simulation for this request

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION F — MIROFISH DEPLOYMENT (docker-compose)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Add the following service to docker-compose.yml so MiroFish runs alongside GOE-1:

  mirofish:
    image: ghcr.io/666ghj/mirofish:latest
    # Alternatively, build from source:
    # build:
    #   context: ./mirofish
    #   dockerfile: Dockerfile
    ports:
      - "5001:5001"
    environment:
      LLM_API_KEY: ${LLM_API_KEY:-${ANTHROPIC_API_KEY}}
      LLM_BASE_URL: ${LLM_BASE_URL:-https://api.anthropic.com/v1}
      LLM_MODEL_NAME: ${LLM_MODEL_NAME:-claude-sonnet-4-20250514}
      ZEP_API_KEY: ${ZEP_API_KEY:-}
      # MiroFish uses OpenAI-SDK-compatible APIs.
      # GOE already has ANTHROPIC_API_KEY — use it here via a compatibility proxy,
      # OR set LLM_BASE_URL to point at Ollama: http://ollama:11434/v1
    depends_on:
      - redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  NOTE: MiroFish natively supports OpenAI-SDK-format LLMs. Since GOE-1 already runs
  Ollama (OLLAMA_URL=http://localhost:11434), you can point MiroFish at Ollama by setting:
    LLM_BASE_URL=http://ollama:11434/v1
    LLM_MODEL_NAME=llama3.1:8b
    LLM_API_KEY=ollama   # any non-empty string
  This avoids duplicate API costs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION G — ZEP MEMORY INTEGRATION (optional but recommended)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MiroFish uses Zep Cloud for long-term agent memory. This is optional but significantly
improves simulation quality. Add to config.py:

  MIROFISH_ZEP_API_KEY: Optional[str] = None

And to .env.example:
  MIROFISH_ZEP_API_KEY=   # get free tier at https://app.getzep.com/

Pass this to the docker-compose MiroFish service as ZEP_API_KEY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION H — FALLBACK BEHAVIOUR & SAFETY GUARANTEES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The MiroFish plugin MUST NEVER break the existing scenario endpoint. Enforce these
invariants in your implementation:

1. If MIROFISH_ENABLED is False (default), the endpoint behaves exactly as before.
   swarm_simulation will be {"plugin": "mirofish", "status": "disabled"}.
   The "tree" field is identical to the original response.

2. If MiroFish is enabled but unreachable (is_available() returns False),
   swarm_simulation is {"plugin": "mirofish", "status": "unavailable"}.
   The "tree" field still returns the full GOE probability tree.

3. If MiroFish times out (simulation takes longer than MIROFISH_TIMEOUT_SECONDS),
   swarm_simulation is {"plugin": "mirofish", "status": "timeout"}.
   The "tree" field still returns the GOE tree (asyncio.gather uses a try/except).

4. All MiroFish exceptions must be caught inside run_simulation and never propagate
   to the endpoint handler.

5. The merge step (_merge_swarm_into_tree) must guard against missing keys with
   .get() defaults and never raise KeyError.

6. Log all MiroFish events under the logger name "goe.mirofish" at appropriate levels:
   INFO for successful simulations, WARNING for unavailability, ERROR for exceptions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION I — API RESPONSE SHAPE (final merged response)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

After integration, POST /analyst/scenario should return:

  {
    "tree": {
      // All existing GOE probability tree fields (unchanged):
      "hypothesis": "...",
      "timeline": "...",
      "confidence": 65,
      "branches": [
        {
          // All existing branch fields (unchanged):
          "id": "branch_a",
          "label": "...",
          "probability": 45,
          "india_impact_score": 78,
          "india_impact": "CRITICAL",
          "india_effects": [...],
          "timeline": "72 hours",
          "key_actors": [...],
          "recommended_response": "...",
          "historical_analog": "...",
          "sub_branches": [],

          // NEW fields added by MiroFish merge:
          "swarm_probability": 42,          // agent-consensus probability for this branch
          "swarm_actor_consensus": "...",   // what simulated actors agreed on
          "swarm_validated": true           // whether swarm data was available for this branch
        },
        ...
      ],
      "india_net_assessment": "...",
      "generated_at": "...",
      "id": "...",

      // NEW top-level swarm fields added by merge:
      "swarm_summary": "...",
      "swarm_key_findings": ["...", "...", "..."],
      "dominant_narrative": "...",
      "dissenting_views": ["...", "..."],
      "swarm_simulation_stats": { "rounds_completed": 10, "agents_active": 500 }
    },

    // Full raw MiroFish plugin output (for frontend transparency panel):
    "swarm_simulation": {
      "plugin": "mirofish",
      "status": "success",
      "swarm_summary": "...",
      "swarm_key_findings": [...],
      "swarm_predicted_outcomes": [...],
      "dominant_narrative": "...",
      "dissenting_views": [...],
      "simulation_stats": { "rounds_completed": 10, "agents_active": 500, "time_seconds": 87 },
      "raw_sample": [...]
    },

    "plugin_status": "success"   // top-level convenience field
  }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION J — TESTS TO WRITE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create apps/api/tests/test_mirofish_plugin.py with the following test cases:

1. test_plugin_disabled: With MIROFISH_ENABLED=False, POST /analyst/scenario returns
   the standard tree and plugin_status="disabled".

2. test_plugin_unavailable: With MIROFISH_ENABLED=True but MiroFish unreachable,
   returns plugin_status="unavailable" and the GOE tree is still present and valid.

3. test_plugin_success (mock): Mock aiohttp to return a valid MiroFish response.
   Assert that swarm fields are merged into tree branches.

4. test_plugin_timeout (mock): Mock aiohttp to raise asyncio.TimeoutError.
   Assert plugin_status="timeout" and tree is still returned.

5. test_merge_swarm_into_tree: Unit test _merge_swarm_into_tree with a fixture tree
   and fixture swarm dict. Assert all new fields are present with correct values.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION K — OPTIONAL FRONTEND ADDITIONS (index.html)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The GOE frontend is in index.html. When the scenario endpoint returns swarm data,
the UI should optionally display:

1. A "Swarm Intelligence" badge on the Scenarios panel header, shown only when
   plugin_status === "success".

2. For each branch card, show a secondary probability bar labelled "Swarm:" alongside
   the GOE probability bar, using the swarm_probability field.

3. A collapsible "Swarm Report" section below the branches that shows:
   - swarm_summary
   - swarm_key_findings as a bullet list
   - dominant_narrative
   - dissenting_views as a collapsible sub-section
   - simulation_stats (rounds, agents)

4. A loading spinner while awaiting swarm results (note: since both run concurrently
   server-side, the spinner shows until the full response arrives).

This is optional. The backend integration is the primary deliverable.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION L — IMPLEMENTATION ORDER (recommended)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Follow this order to avoid breaking the running system:

Step 1: Add MIROFISH_* settings to config.py (non-breaking, all default to off).
Step 2: Create mirofish_plugin.py with MIROFISH_ENABLED=False behaviour first
        (just returns {status: "disabled"} early). Run existing tests — all must pass.
Step 3: Implement the full run_simulation method using mock MiroFish responses.
Step 4: Update routers/analyst.py with the new run_scenario endpoint.
Step 5: Update schemas/analyst.py with the optional use_swarm field.
Step 6: Add MiroFish service to docker-compose.yml.
Step 7: Add to main.py lifespan startup.
Step 8: Write tests in test_mirofish_plugin.py.
Step 9: Set MIROFISH_ENABLED=true in .env and test end-to-end with a live scenario.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION M — EXAMPLE SCENARIO CALL & EXPECTED ENRICHMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Example request:
  POST /analyst/scenario
  {
    "hypothesis": "China imposes naval blockade on Taiwan Strait affecting Indian shipping",
    "depth": 3,
    "use_swarm": true
  }

Expected GOE tree (existing behaviour):
  Branch A (45%): Full military confrontation — India Impact CRITICAL
  Branch B (35%): Diplomatic resolution — India Impact HIGH
  Branch C (20%): Prolonged standoff — India Impact MEDIUM

Expected MiroFish swarm enrichment (new behaviour):
  After spawning 500 agents (Indian policy analysts, Chinese PLA strategists, US
  Naval officials, Pakistani ISI analysts, shipping executives, journalists etc.)
  and running 10 rounds of social simulation, the swarm may surface:

  - Dominant narrative: "Most agents converge on Indian Navy deploying QUAD
    coordination, rerouting via Lombok Strait within 48 hours"
  - Dissenting view: "3% of market-trader agents predict INR spike, triggering
    RBI intervention that is not captured in GOE branches"
  - Swarm probability for Branch A: 38% (lower than GOE's 45%, indicating
    agent interactions suggest diplomatic back-channels are more active)
  - Key finding: "Social media agents simulate massive protest in Mumbai port
    communities — a second-order effect not in the GOE tree"

This emergent intelligence, unavailable from a single LLM call, is the core
value MiroFish adds to GOE's Scenarios feature.

END OF INTEGRATION PROMPT
```

---

## 3. Quick Reference: File Change Summary

| File | Change Type | Purpose |
|------|-------------|---------|
| `apps/api/core/analyst/mirofish_plugin.py` | **CREATE** | MiroFish HTTP client + simulation runner |
| `apps/api/config.py` | **MODIFY** | Add 6 MIROFISH_* settings |
| `apps/api/.env.example` | **MODIFY** | Document new env vars |
| `apps/api/main.py` | **MODIFY** | Initialise plugin in app lifespan |
| `apps/api/routers/analyst.py` | **MODIFY** | Concurrent GOE + MiroFish execution |
| `apps/api/schemas/analyst.py` | **MODIFY** | Add optional `use_swarm` field |
| `docker-compose.yml` | **MODIFY** | Add MiroFish service |
| `apps/api/tests/test_mirofish_plugin.py` | **CREATE** | 5 test cases |

---

## 4. Key Design Decisions

**Why concurrent execution?** MiroFish simulations with 500 agents and 10 rounds can take 60–120 seconds. Running it in parallel with the GOE tree (which returns in ~3s) means the total latency is bounded by MiroFish, not additive. If MiroFish times out, the user still gets the GOE result immediately.

**Why OpenAI-SDK compatibility matters?** GOE already has Ollama running with `llama3.1:8b`. MiroFish can be pointed at the same Ollama instance using `http://ollama:11434/v1` as the base URL, avoiding any new API costs or keys.

**Why not embed MiroFish's Python code directly?** MiroFish is a full application (Flask + Vue frontend + Zep memory + OASIS simulation). Running it as a separate service via HTTP is cleaner, allows independent scaling, and keeps the GOE API stateless. The plugin is purely an HTTP adapter.

**Why feature-flag default to disabled?** MiroFish simulations consume significant LLM tokens (500 agents × 10 rounds = potentially thousands of API calls). Defaulting to `MIROFISH_ENABLED=false` protects against surprise costs in production.
