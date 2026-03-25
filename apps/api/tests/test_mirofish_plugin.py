"""
Tests for the MiroFish swarm-intelligence plugin integration.

Tests cover:
  1. Plugin disabled → original behaviour preserved
  2. Plugin enabled but unreachable → graceful degradation
  3. Plugin success (mocked) → swarm fields merged into tree
  4. Plugin timeout (mocked) → timeout status, GOE tree intact
  5. _merge_swarm_into_tree unit test
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers import analyst
from apps.api.routers.analyst import _merge_swarm_into_tree


# ── Fixtures & Helpers ─────────────────────────────────────────────

FIXTURE_GOE_TREE = {
    "hypothesis": "Test scenario",
    "timeline": "2-4 weeks",
    "confidence": 65,
    "branches": [
        {
            "id": "branch_a",
            "label": "Branch A - Escalation",
            "probability": 45,
            "india_impact_score": 78,
            "india_impact": "CRITICAL",
            "india_effects": ["effect1"],
            "timeline": "72 hours",
            "key_actors": ["actor1"],
            "recommended_response": "response",
            "historical_analog": "Similar to: Event X",
            "sub_branches": [],
        },
        {
            "id": "branch_b",
            "label": "Branch B - De-escalation",
            "probability": 35,
            "india_impact_score": 45,
            "india_impact": "HIGH",
            "india_effects": ["effect2"],
            "timeline": "2 weeks",
            "key_actors": ["actor2"],
            "recommended_response": "response",
            "historical_analog": "Similar to: Event Y",
            "sub_branches": [],
        },
        {
            "id": "branch_c",
            "label": "Branch C - Standoff",
            "probability": 20,
            "india_impact_score": 30,
            "india_impact": "MEDIUM",
            "india_effects": ["effect3"],
            "timeline": "3 months",
            "key_actors": ["actor3"],
            "recommended_response": "response",
            "historical_analog": "Similar to: Event Z",
            "sub_branches": [],
        },
    ],
    "india_net_assessment": "Net assessment text.",
    "generated_at": "2026-03-24T00:00:00+00:00",
    "id": "test-id",
}

FIXTURE_SWARM_RESULT = {
    "plugin": "mirofish",
    "status": "success",
    "swarm_summary": "Agents converge on diplomatic resolution.",
    "swarm_key_findings": [
        "Indian Navy activates QUAD coordination",
        "INR experiences 2% depreciation",
        "Media agents simulate widespread protest",
    ],
    "swarm_predicted_outcomes": [
        {"label": "Escalation", "probability": 38, "actor_consensus": "Military takeover unlikely"},
        {"label": "De-escalation", "probability": 42, "actor_consensus": "Diplomatic channels active"},
        {"label": "Standoff", "probability": 20, "actor_consensus": "Status quo maintained"},
    ],
    "dominant_narrative": "Diplomatic back-channels prevent escalation",
    "dissenting_views": ["3% of agents predict surprise military action"],
    "simulation_stats": {"rounds_completed": 10, "agents_active": 500, "time_seconds": 87},
    "raw_sample": [{"agent": "Indian policy analyst", "message": "QUAD meeting called"}],
    "error": None,
}


class FakeRedis:
    async def get(self, key):
        return None

    async def set(self, key, value):
        pass


class FakeVector:
    def query(self, text, n_results=5):
        return [{"document": "Test doc", "source": "TEST", "domain": "GEOPOLITICS", "severity": 3}]

    def count(self):
        return 1


class FakeScenarioEngine:
    def __init__(self, **kwargs):
        pass

    async def generate_scenario_tree(self, hypothesis, depth=3):
        import copy
        return copy.deepcopy(FIXTURE_GOE_TREE)


class FakeEngine:
    class _LLM:
        _mode = "none"
    _llm = _LLM()


def _make_mirofish_plugin(enabled=False):
    from apps.api.core.analyst.mirofish_plugin import MiroFishPlugin
    return MiroFishPlugin(config={
        "mirofish_url": "http://localhost:5001",
        "mirofish_api_key": None,
        "num_agents": 500,
        "simulation_rounds": 10,
        "timeout_seconds": 120,
        "enabled": enabled,
    })


def build_app(mirofish_enabled=False):
    """Build a test FastAPI app with the analyst router."""
    app = FastAPI()
    app.state.redis = FakeRedis()
    app.state.vector = FakeVector()
    app.state.engine = FakeEngine()
    app.state.mirofish = _make_mirofish_plugin(enabled=mirofish_enabled)
    app.include_router(analyst.router, prefix="/api/v1/analyst")
    return app


# ── Tests ──────────────────────────────────────────────────────────


def test_plugin_disabled():
    """With MIROFISH_ENABLED=False, endpoint returns standard tree and plugin_status='disabled'."""
    app = build_app(mirofish_enabled=False)

    with patch("apps.api.core.analyst.scenario_engine.ScenarioEngine", FakeScenarioEngine):
        client = TestClient(app)
        response = client.post(
            "/api/v1/analyst/scenario",
            json={"hypothesis": "Test scenario", "depth": 2},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["plugin_status"] == "disabled"
    assert data["swarm_simulation"]["status"] == "disabled"
    assert "tree" in data
    assert data["tree"]["hypothesis"] == "Test scenario"
    assert len(data["tree"]["branches"]) == 3
    # Swarm fields should NOT be in tree when disabled
    assert "swarm_summary" not in data["tree"]


def test_plugin_unavailable():
    """With MIROFISH_ENABLED=True but MiroFish unreachable, returns unavailable status."""
    app = build_app(mirofish_enabled=True)

    with patch("apps.api.core.analyst.scenario_engine.ScenarioEngine", FakeScenarioEngine):
        # Mock aiohttp to simulate unreachable MiroFish
        with patch("apps.api.core.analyst.mirofish_plugin.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_get = AsyncMock(side_effect=OSError("Connection refused"))
            mock_session.get = mock_get
            mock_session_cls.return_value = mock_session

            # We need to reset the plugin's session
            app.state.mirofish._session = None

            client = TestClient(app)
            response = client.post(
                "/api/v1/analyst/scenario",
                json={"hypothesis": "Test unreachable", "depth": 2},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["plugin_status"] == "unavailable"
    assert data["swarm_simulation"]["status"] == "unavailable"
    assert "tree" in data
    assert data["tree"]["hypothesis"] == "Test scenario"


def test_plugin_success():
    """Mock a successful MiroFish response and verify swarm fields are merged."""
    app = build_app(mirofish_enabled=True)
    plugin = app.state.mirofish

    # Directly mock the plugin's run_simulation to return our fixture
    import copy
    plugin.run_simulation = AsyncMock(return_value=copy.deepcopy(FIXTURE_SWARM_RESULT))

    with patch("apps.api.core.analyst.scenario_engine.ScenarioEngine", FakeScenarioEngine):
        client = TestClient(app)
        response = client.post(
            "/api/v1/analyst/scenario",
            json={"hypothesis": "China blockade Taiwan", "depth": 3, "use_swarm": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["plugin_status"] == "success"

    # Verify swarm fields are merged into tree
    tree = data["tree"]
    assert tree["swarm_summary"] == "Agents converge on diplomatic resolution."
    assert len(tree["swarm_key_findings"]) == 3
    assert tree["dominant_narrative"] == "Diplomatic back-channels prevent escalation"
    assert len(tree["dissenting_views"]) == 1

    # Verify branch-level swarm enrichment
    branches = tree["branches"]
    assert branches[0]["swarm_probability"] == 38
    assert branches[0]["swarm_validated"] is True
    assert branches[1]["swarm_probability"] == 42
    assert branches[2]["swarm_probability"] == 20

    # Verify full swarm simulation output
    swarm = data["swarm_simulation"]
    assert swarm["plugin"] == "mirofish"
    assert swarm["status"] == "success"
    assert len(swarm["raw_sample"]) == 1


def test_plugin_timeout():
    """Mock asyncio.TimeoutError and verify graceful degradation."""
    app = build_app(mirofish_enabled=True)
    plugin = app.state.mirofish

    # Mock run_simulation to return a timeout result
    plugin.run_simulation = AsyncMock(return_value={
        "plugin": "mirofish",
        "status": "timeout",
        "swarm_summary": "",
        "swarm_key_findings": [],
        "swarm_predicted_outcomes": [],
        "dominant_narrative": "",
        "dissenting_views": [],
        "simulation_stats": {},
        "raw_sample": [],
        "error": "Timed out after 120s",
    })

    with patch("apps.api.core.analyst.scenario_engine.ScenarioEngine", FakeScenarioEngine):
        client = TestClient(app)
        response = client.post(
            "/api/v1/analyst/scenario",
            json={"hypothesis": "Test timeout", "depth": 2, "use_swarm": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["plugin_status"] == "timeout"
    assert data["swarm_simulation"]["status"] == "timeout"
    # GOE tree should still be fully present
    assert "tree" in data
    assert len(data["tree"]["branches"]) == 3
    # Swarm fields should NOT be merged on timeout
    assert "swarm_summary" not in data["tree"]


def test_merge_swarm_into_tree():
    """Unit test the _merge_swarm_into_tree helper with fixture data."""
    import copy
    tree = copy.deepcopy(FIXTURE_GOE_TREE)
    swarm = copy.deepcopy(FIXTURE_SWARM_RESULT)

    merged = _merge_swarm_into_tree(tree, swarm)

    # Top-level swarm fields
    assert merged["swarm_summary"] == "Agents converge on diplomatic resolution."
    assert len(merged["swarm_key_findings"]) == 3
    assert merged["dominant_narrative"] == "Diplomatic back-channels prevent escalation"
    assert merged["dissenting_views"] == ["3% of agents predict surprise military action"]
    assert merged["swarm_simulation_stats"]["rounds_completed"] == 10
    assert merged["swarm_simulation_stats"]["agents_active"] == 500

    # Branch-level enrichment
    branches = merged["branches"]
    assert branches[0]["swarm_probability"] == 38
    assert branches[0]["swarm_actor_consensus"] == "Military takeover unlikely"
    assert branches[0]["swarm_validated"] is True

    assert branches[1]["swarm_probability"] == 42
    assert branches[1]["swarm_actor_consensus"] == "Diplomatic channels active"
    assert branches[1]["swarm_validated"] is True

    assert branches[2]["swarm_probability"] == 20
    assert branches[2]["swarm_validated"] is True

    # Original fields should be preserved
    assert merged["hypothesis"] == "Test scenario"
    assert merged["confidence"] == 65
    assert len(branches) == 3
    assert branches[0]["india_impact"] == "CRITICAL"


def test_merge_swarm_into_tree_missing_outcomes():
    """Test merge with fewer swarm outcomes than branches (graceful handling)."""
    import copy
    tree = copy.deepcopy(FIXTURE_GOE_TREE)
    swarm = {
        "swarm_summary": "Partial data",
        "swarm_key_findings": [],
        "dominant_narrative": "",
        "dissenting_views": [],
        "swarm_predicted_outcomes": [
            {"label": "Only one", "probability": 50, "actor_consensus": "Partial"},
        ],
        "simulation_stats": {},
    }

    merged = _merge_swarm_into_tree(tree, swarm)

    # First branch should have swarm data
    assert merged["branches"][0]["swarm_probability"] == 50
    assert merged["branches"][0]["swarm_validated"] is True

    # Remaining branches should gracefully handle missing data
    assert merged["branches"][1]["swarm_probability"] is None
    assert merged["branches"][1]["swarm_validated"] is False
    assert merged["branches"][2]["swarm_probability"] is None
    assert merged["branches"][2]["swarm_validated"] is False
