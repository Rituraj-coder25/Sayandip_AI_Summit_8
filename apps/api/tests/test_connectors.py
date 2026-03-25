import asyncio

from apps.api.ingestion.base_connector import BaseConnector


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def hset(self, key, mapping):
        self.hashes[key] = mapping

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)


class DummyHttp:
    async def get(self, url, **kwargs):
        raise AssertionError("HTTP should not be called in this unit test")


class DummyConnector(BaseConnector):
    SOURCE_NAME = "dummy"
    POLL_INTERVAL_SECONDS = 0

    async def fetch(self):
        return {"items": [1]}

    async def parse(self, payload):
        return [{"id": "1", "source_name": "dummy", "title": "ok"}]


def test_base_connector_marks_health_and_returns_items():
    connector = DummyConnector(FakeRedis(), DummyHttp())
    items = asyncio.run(connector.run())
    assert len(items) == 1
    assert connector.redis.hashes["goe:source_health:dummy"]["status"] == "healthy"
