"""
Bharatiya Language Intelligence Pipeline.
Detects non-English signals from Bharatiya feeds and translates them before
routing them into the main intelligence pipeline.
"""
from __future__ import annotations

import json
import logging
import re

try:
    from langdetect import LangDetectException, detect
except Exception:
    LangDetectException = Exception

    def detect(_text: str) -> str:
        return "en"

logger = logging.getLogger("goe.bharatiya")

SUPPORTED_LANGUAGES = {
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "ur": "Urdu",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
}


def detect_language(text: str) -> str:
    if not text or len(text) < 20:
        return "en"
    try:
        return detect(text)
    except LangDetectException:
        return "en"
    except Exception:
        return "en"


def is_bharatiya(text: str) -> bool:
    return detect_language(text) in SUPPORTED_LANGUAGES


async def translate_and_enrich(raw_signal: dict, llm) -> dict:
    text = f"{raw_signal.get('title', '')} {raw_signal.get('summary', '')}".strip()
    lang = detect_language(text)
    if lang not in SUPPORTED_LANGUAGES:
        return raw_signal

    lang_name = SUPPORTED_LANGUAGES[lang]
    logger.info("Translating %s signal: %s", lang_name, raw_signal.get("title", "")[:50])

    prompt = f"""You are translating a {lang_name} news item for an Indian government intelligence system.

ORIGINAL {lang_name.upper()} TEXT:
Title: {raw_signal.get('title', '')}
Summary: {raw_signal.get('summary', '')[:400]}

Provide:
1. English translation of the title
2. English translation of the summary (2-3 sentences max)
3. India relevance score (0-100): how much does this affect India?
4. Domain: geopolitics | economics | defense | technology | climate | society

Return ONLY JSON:
{{"en_title":"...","en_summary":"...","india_score":0,"domain":"..."}}"""

    result = await llm.complete(prompt, max_tokens=250, prefer_fast=True)
    if not result:
        raw_signal["translated"] = False
        raw_signal["original_lang"] = lang
        return raw_signal

    raw_json = result.strip()
    if raw_json.startswith("```"):
        raw_json = raw_json.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw_json)
        parsed = json.loads(match.group()) if match else {}

    if parsed:
        raw_signal["title"] = parsed.get("en_title", raw_signal.get("title", ""))
        raw_signal["summary"] = parsed.get("en_summary", raw_signal.get("summary", ""))
        raw_signal["india_score"] = int(parsed.get("india_score", raw_signal.get("india_score", 40)))
        raw_signal["domain"] = parsed.get("domain", raw_signal.get("domain", "geopolitics"))
        raw_signal["translated"] = True
        raw_signal["original_lang"] = lang
        raw_signal["original_title"] = raw_signal.get("original_title") or text[:100]
    else:
        raw_signal["translated"] = False
        raw_signal["original_lang"] = lang

    return raw_signal