"""
MiroFish Swarm-Intelligence Plugin for GOE-1 Scenarios.

Communicates with the MiroFish Flask backend via HTTP to spawn
multi-agent simulations that enrich the ScenarioEngine probability tree.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger("goe.mirofish")


class MiroFishPlugin:
    """HTTP adapter for the MiroFish swarm-intelligence simulation engine."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._mirofish_url: str = config.get("mirofish_url", "http://localhost:5001")
        self._api_key: str | None = config.get("mirofish_api_key")
        self.num_agents: int = min(config.get("num_agents", 500), 5000)
        self.simulation_rounds: int = config.get("simulation_rounds", 10)
        self._timeout: int = config.get("timeout_seconds", 120)
        self._enabled: bool = config.get("enabled", False)
        self._session: aiohttp.ClientSession | None = None

    # ── helpers ──────────────────────────────────────────────────────

    def _get_session(self) -> aiohttp.ClientSession:
        """Create an aiohttp session lazily."""
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    @staticmethod
    def _empty_result(status: str, error: str | None = None) -> dict:
        """Return the structured enrichment dict with empty values."""
        return {
            "plugin": "mirofish",
            "status": status,
            "swarm_summary": "",
            "swarm_key_findings": [],
            "swarm_predicted_outcomes": [],
            "dominant_narrative": "",
            "dissenting_views": [],
            "simulation_stats": {},
            "raw_sample": [],
            "error": error,
        }

    # ── public API ──────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """Check whether the MiroFish backend is reachable (5s timeout)."""
        if not self._enabled:
            return False
        try:
            session = self._get_session()
            # Try /health first, fall back to /api/status
            for path in ("/health", "/api/status"):
                try:
                    async with session.get(
                        f"{self._mirofish_url}{path}",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    continue
            logger.warning("MiroFish backend not reachable at %s", self._mirofish_url)
            return False
        except Exception as exc:
            logger.warning("MiroFish availability check failed: %s", exc)
            return False

    async def run_simulation(
        self, hypothesis: str, context_signals: list[dict]
    ) -> dict:
        """
        Run a full MiroFish swarm simulation for the given hypothesis.

        Returns a structured enrichment dict regardless of success or failure.
        This method NEVER raises — all exceptions are caught and logged.
        """
        if not self._enabled:
            return self._empty_result("disabled")

        try:
            # Check availability first
            if not await self.is_available():
                return self._empty_result("unavailable")

            # STEP 1 — Build seed material
            seed = self._build_seed(hypothesis, context_signals)

            # STEP 2 — Submit simulation job
            raw_result = await self._submit_and_poll(seed)

            # STEP 3 — Parse MiroFish output
            parsed = self._parse_output(raw_result)

            # STEP 4 — Return structured enrichment
            logger.info(
                "MiroFish simulation complete: %d agents, %d rounds",
                parsed.get("simulation_stats", {}).get("agents_active", 0),
                parsed.get("simulation_stats", {}).get("rounds_completed", 0),
            )
            return parsed

        except asyncio.TimeoutError:
            logger.error("MiroFish simulation timed out after %ds", self._timeout)
            return self._empty_result("timeout", f"Timed out after {self._timeout}s")
        except Exception as exc:
            logger.error("MiroFish simulation failed: %s", exc, exc_info=True)
            return self._empty_result("error", str(exc))

    # ── internal steps ──────────────────────────────────────────────

    def _build_seed(self, hypothesis: str, context_signals: list[dict]) -> str:
        """STEP 1 — Construct seed document from hypothesis + RAG signals."""
        signal_lines: list[str] = []
        for sig in context_signals[:5]:
            source = sig.get("source", "UNKNOWN")
            domain = sig.get("domain", "GENERAL")
            severity = sig.get("severity", "N/A")
            text = sig.get("document", sig.get("text", ""))[:200]
            signal_lines.append(f"- [{source} | {domain} | SEVERITY:{severity}] {text}")

        signals_block = "\n".join(signal_lines) if signal_lines else "No signals available."

        prediction_question = (
            "Given this scenario, simulate how key actors (governments, military, "
            "markets, media, civilian populations) will respond over the next "
            "72 hours to 3 months. Focus on India's geopolitical exposure."
        )

        return (
            f"=== GOE GEOPOLITICAL SCENARIO SEED ===\n"
            f"SCENARIO: {hypothesis}\n"
            f"DATE: {datetime.now(timezone.utc).isoformat()}\n"
            f"\n"
            f"RELEVANT INTELLIGENCE SIGNALS:\n"
            f"{signals_block}\n"
            f"\n"
            f"PREDICTION QUESTION:\n"
            f'"{prediction_question}"'
        )

    async def _submit_and_poll(self, seed: str) -> dict[str, Any]:
        """STEP 2 — POST simulation job, poll if async (202)."""
        session = self._get_session()
        timeout = aiohttp.ClientTimeout(total=self._timeout)

        prediction_question = (
            "Given this scenario, simulate how key actors (governments, military, "
            "markets, media, civilian populations) will respond over the next "
            "72 hours to 3 months. Focus on India's geopolitical exposure."
        )

        payload = {
            "seed_material": seed,
            "prediction_question": prediction_question,
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
                "Central bank governor",
            ],
            "output_format": "json",
        }

        async with session.post(
            f"{self._mirofish_url}/api/simulate",
            json=payload,
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()

            if resp.status == 202:
                data = await resp.json()
                job_id = data.get("job_id")
                if not job_id:
                    raise ValueError("MiroFish returned 202 but no job_id")
                return await self._poll_job(job_id, timeout)

            text = await resp.text()
            raise RuntimeError(
                f"MiroFish returned unexpected HTTP {resp.status}: {text[:200]}"
            )

    async def _poll_job(
        self, job_id: str, timeout: aiohttp.ClientTimeout
    ) -> dict[str, Any]:
        """Poll a MiroFish async job until complete or timeout."""
        session = self._get_session()
        poll_url = f"{self._mirofish_url}/api/simulate/{job_id}/status"
        deadline = asyncio.get_event_loop().time() + self._timeout

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(10)
            async with session.get(poll_url, timeout=timeout) as resp:
                data = await resp.json()
                status = data.get("status", "")
                if status == "complete":
                    return data.get("result", data)
                if status in ("failed", "error"):
                    raise RuntimeError(f"MiroFish job {job_id} failed: {data}")

        raise asyncio.TimeoutError(f"MiroFish job {job_id} timed out")

    def _parse_output(self, raw: dict[str, Any]) -> dict:
        """STEP 3+4 — Parse MiroFish response into structured enrichment dict."""
        report = raw.get("report", {})
        consensus = raw.get("agent_consensus", {})
        stats = raw.get("simulation_stats", {})
        interactions = raw.get("raw_interactions_sample", [])

        return {
            "plugin": "mirofish",
            "status": "success",
            "swarm_summary": report.get("summary", ""),
            "swarm_key_findings": report.get("key_findings", [])[:5],
            "swarm_predicted_outcomes": report.get("predicted_outcomes", []),
            "dominant_narrative": consensus.get("dominant_narrative", ""),
            "dissenting_views": consensus.get("dissenting_views", []),
            "simulation_stats": stats,
            "raw_sample": interactions[:3],
            "error": None,
        }
