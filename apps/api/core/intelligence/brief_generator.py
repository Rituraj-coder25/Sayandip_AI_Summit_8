"""
Unified LLM client plus structured brief generation.
The client prefers Ollama when available and falls back to Anthropic if configured.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("goe.llm")


class LLMClient:
    def __init__(
        self,
        ollama_url: str,
        ollama_model: str,
        anthropic_key: Optional[str] = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.anthropic_key = anthropic_key
        self._mode = "detecting"
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_http = http_client is None

    async def detect_mode(self) -> str:
        try:
            response = await self._http.get(f"{self.ollama_url}/api/tags", timeout=3.0)
            if response.status_code == 200:
                models = [model.get("name", "") for model in response.json().get("models", [])]
                target = self.ollama_model.split(":")[0]
                if any(target in model for model in models):
                    self._mode = "ollama"
                    logger.info("LLM mode: Ollama (%s)", self.ollama_model)
                    return self._mode
        except Exception:
            pass

        if self.anthropic_key:
            self._mode = "anthropic"
            logger.info("LLM mode: Anthropic API")
            return self._mode

        self._mode = "none"
        logger.warning("LLM mode: NONE - AI completions unavailable")
        return self._mode

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 800,
        prefer_fast: bool = False,
    ) -> str | None:
        if self._mode == "detecting":
            await self.detect_mode()

        if self._mode == "ollama":
            return await self._ollama(prompt, system, max_tokens)
        if self._mode == "anthropic":
            return await self._anthropic(prompt, system, max_tokens, prefer_fast)
        return None

    async def _ollama(self, prompt: str, system: str, max_tokens: int) -> str | None:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        try:
            response = await self._http.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.4},
                },
            )
            response.raise_for_status()
            return response.json().get("response", "").strip() or None
        except Exception as exc:
            logger.error("Ollama call failed: %s", exc)
            return None

    async def _anthropic(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        prefer_fast: bool,
    ) -> str | None:
        model = "claude-haiku-4-5-20251001" if prefer_fast else "claude-sonnet-4-20250514"
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
            message = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text if message.content else None
        except Exception as exc:
            logger.error("Anthropic call failed: %s", exc)
            return None

    async def close(self):
        if self._owns_http:
            await self._http.aclose()


class BriefGenerator:
    SEVERITY_THRESHOLD = 45

    def __init__(self, llm: LLMClient, vector_store):
        self.llm = llm
        self.vector = vector_store

    async def generate(
        self,
        text: str,
        entities: list,
        domain: str,
        severity: int,
        india_score: int,
    ) -> dict | None:
        if severity < self.SEVERITY_THRESHOLD and india_score < 65:
            return None

        similar = self.vector.query(text, n_results=3, where={"domain": domain})
        rag_lines = [f"- {item['document'][:150]}" for item in similar]
        rag_ctx = "\n".join(rag_lines) or "No similar historical events found."
        prefer_fast = severity < 70 and india_score < 70

        prompt = f"""Analyse this intelligence signal for Indian government decision-makers.

SIGNAL: {text[:700]}
DOMAIN: {domain.upper()} | SEVERITY: {severity}/100 | INDIA RELEVANCE: {india_score}/100
ENTITIES: {', '.join(entity.get('text', '') for entity in entities[:8])}

RELATED HISTORICAL CONTEXT:
{rag_ctx}

Return ONLY a JSON object - no markdown fences, no preamble:
{{
  "headline": "12-word maximum factual headline",
  "summary": "2-3 sentences: what happened, who is involved, why it matters",
  "india_impact": "1-2 sentences: specific effect on India interests or security",
  "key_actors": ["up to 5 actors"],
  "trend": "ESCALATING | STABLE | DE-ESCALATING",
  "recommended_watch": "one specific thing to monitor in next 48-72 hours",
  "confidence": 0
}}"""

        raw = await self.llm.complete(prompt, max_tokens=600, prefer_fast=prefer_fast)
        if not raw:
            return None

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            logger.warning("Brief JSON parse failed. Raw: %s", cleaned[:100])
            return {
                "headline": text[:80],
                "summary": text[:300],
                "india_impact": "Assessment pending.",
                "key_actors": [entity.get("text", "") for entity in entities[:3]],
                "trend": "STABLE",
                "recommended_watch": "Monitor for updates.",
                "confidence": 20,
            }