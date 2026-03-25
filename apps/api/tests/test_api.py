import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers import admin, analyst, india


class FakeRedis:
    def __init__(self):
        self.values = {
            "goe:market_snapshot": json.dumps({"NIFTY": "Last price 22000"}),
            "goe:india_risk_score_full": json.dumps({"score": 42, "color": "amber"}),
            "goe:india_risk_score": "42",
            "goe:stats:signals_today": "7",
        }
        self.hashes = {}
        self.feedback = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def lpush(self, key, value):
        if key == "goe:analyst_feedback":
            self.feedback.insert(0, value)

    async def ltrim(self, key, start, end):
        if key == "goe:analyst_feedback":
            self.feedback = self.feedback[start : end + 1]

    async def llen(self, key):
        return len(self.feedback) if key == "goe:analyst_feedback" else 0

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])


class FakeVector:
    def count(self):
        return 3

    def query(self, *args, **kwargs):
        return []


class FakeScheduler:
    connectors = {str(index): object() for index in range(14)}

    async def force_run(self, name: str):
        return None


class FakeEngine:
    class _LLM:
        _mode = "none"

    _llm = _LLM()


class FakeAnalyst:
    async def query(self, question: str, user_role: str, conversation_history: list[dict]):
        return {"response": "ok"}


def build_app():
    app = FastAPI()
    app.state.redis = FakeRedis()
    app.state.vector = FakeVector()
    app.state.neo4j = None
    app.state.scheduler = FakeScheduler()
    app.state.engine = FakeEngine()
    app.state.analyst = FakeAnalyst()
    app.include_router(india.router, prefix="/api/v1/india")
    app.include_router(admin.router, prefix="/api/v1/admin")
    app.include_router(analyst.router, prefix="/api/v1/analyst")
    return app


def test_india_markets_endpoint_returns_cached_snapshot():
    client = TestClient(build_app())
    response = client.get("/api/v1/india/markets")
    assert response.status_code == 200
    assert response.json()["NIFTY"] == "Last price 22000"


def test_admin_stats_endpoint_uses_state_services():
    client = TestClient(build_app())
    response = client.get("/api/v1/admin/stats")
    assert response.status_code == 200
    assert response.json()["signals_today"] == 7
    assert response.json()["vectors_stored"] == 3
    assert response.json()["connectors"] == 14


def test_feedback_endpoint_records_rating():
    client = TestClient(build_app())
    response = client.post(
        "/api/v1/analyst/feedback",
        json={"response_id": "test_123", "rating": 1, "component": "border", "comment": "accurate"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "recorded"
    assert response.json()["total_ratings"] == 1


def test_analyst_query_endpoint_returns_antigravity_answer():
    client = TestClient(build_app())
    response = client.post(
        "/api/v1/analyst/query",
        json={
            "question": "Explain how current signals affect India's energy security.",
            "context": "INDIA RISK SCORE: 42/100 (AMBER)\nUSD/INR: 83.10",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "antigravity_v1"
    assert "ENERGY SECURITY" in payload["answer"]
