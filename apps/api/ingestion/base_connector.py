import inspect
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

logger = logging.getLogger("goe.connectors")


class BaseConnector(ABC):
    SOURCE_NAME = "base_connector"
    POLL_INTERVAL_SECONDS = 300
    MIN_INTERVAL_SECONDS = None
    CACHE_TTL_SECONDS = 3600

    def __init__(self, redis_client, http_client):
        self.redis = redis_client
        self.http = http_client

    async def run(self) -> list[dict]:
        if not await self._should_fetch():
            return []

        started = time.perf_counter()
        try:
            if self._has_override("fetch_raw"):
                payload = await self.fetch_raw()
            else:
                payload = await self.fetch()
            items = await self._maybe_await(self.parse(payload)) or []
            await self.post_process(items)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            await self._mark_success(len(items), latency_ms)
            await self.redis.set(f"goe:last_fetch:{self.SOURCE_NAME}", time.time())
            if items:
                await self.redis.setex(
                    f"goe:cache:{self.SOURCE_NAME}",
                    self.CACHE_TTL_SECONDS,
                    json.dumps(items, default=str),
                )
            return items
        except Exception as exc:
            await self._mark_error(str(exc))
            logger.exception("Connector %s failed", self.SOURCE_NAME)
            return []

    async def _should_fetch(self) -> bool:
        last_fetch = await self.redis.get(f"goe:last_fetch:{self.SOURCE_NAME}")
        if not last_fetch:
            return True
        interval = self.MIN_INTERVAL_SECONDS or self.POLL_INTERVAL_SECONDS
        try:
            return (time.time() - float(last_fetch)) >= interval
        except ValueError:
            return True

    async def _mark_success(self, count: int, latency_ms: float):
        await self.redis.hset(
            f"goe:source_health:{self.SOURCE_NAME}",
            mapping={
                "status": "healthy",
                "last_success": datetime.now(UTC).isoformat(),
                "last_error": "",
                "items_count": count,
                "latency_ms": latency_ms,
            },
        )

    async def _mark_error(self, message: str):
        await self.redis.hset(
            f"goe:source_health:{self.SOURCE_NAME}",
            mapping={
                "status": "error",
                "last_error": message[:500],
                "last_success": (await self.redis.hget(f"goe:source_health:{self.SOURCE_NAME}", "last_success")) or "",
                "items_count": 0,
            },
        )

    def std_signal(
        self,
        id: str,
        title: str,
        summary: str = "",
        domain: str = "geopolitics",
        severity: int = 30,
        india_score: int = 0,
        url: str = "",
        published_at: str | None = None,
        raw: dict | None = None,
        source_name: str | None = None,
        **extra,
    ) -> dict:
        source_value = source_name or self.SOURCE_NAME
        payload = {
            "id": id,
            "source_name": source_value,
            "source": source_value,
            "title": title,
            "summary": summary,
            "domain": domain,
            "severity": severity,
            "india_score": india_score,
            "source_url": url,
            "url": url,
            "published_at": published_at or datetime.now(UTC).isoformat(),
            "raw": raw or {},
            "raw_text": f"{title} {summary}".strip(),
        }
        payload.update(extra)
        return payload

    async def post_process(self, items: list[dict]):
        return None

    async def fetch_json(self, url: str, **kwargs):
        response = await self.http.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def fetch_text(self, url: str, **kwargs):
        response = await self.http.get(url, **kwargs)
        response.raise_for_status()
        return response.text

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value

    def _has_override(self, method_name: str) -> bool:
        return getattr(self.__class__, method_name) is not getattr(BaseConnector, method_name)

    async def fetch(self):
        raise NotImplementedError

    async def fetch_raw(self):
        raise NotImplementedError

    @abstractmethod
    async def parse(self, payload) -> list[dict]:
        raise NotImplementedError