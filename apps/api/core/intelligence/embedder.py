"""
Singleton sentence-transformer embedder.
Used by: engine.py, vector_store.py, goe_analyst.py, scenario_engine.py
One instance loaded at startup and reused everywhere.
"""
from __future__ import annotations

import hashlib
import logging
import math

logger = logging.getLogger("goe.embedder")

MODEL_NAME = "all-MiniLM-L6-v2"
_DIMENSIONS = 384
_embedder = None


class _FallbackEmbedder:
    """Deterministic hash embedder used when sentence-transformers is unavailable."""

    def encode(self, texts, convert_to_tensor: bool = False):
        if isinstance(texts, str):
            return _hash_embed(texts)
        return [_hash_embed(text) for text in texts]


def get_embedder():
    """Return the singleton embedder, loading it on first call."""
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading sentence transformer: %s", MODEL_NAME)
            _embedder = SentenceTransformer(MODEL_NAME)
            logger.info("Embedder ready")
        except Exception as exc:
            logger.warning("SentenceTransformer unavailable, using fallback embedder: %s", exc)
            _embedder = _FallbackEmbedder()
    return _embedder


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a JSON-serialisable list[float]."""
    value = get_embedder().encode((text or "")[:512], convert_to_tensor=False)
    return value.tolist() if hasattr(value, "tolist") else list(value)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple strings at once."""
    truncated = [(text or "")[:512] for text in texts]
    values = get_embedder().encode(truncated, convert_to_tensor=False)
    return values.tolist() if hasattr(values, "tolist") else [list(row) for row in values]


def _hash_embed(text: str) -> list[float]:
    tokens = (text or "").lower().split()
    vector = [0.0] * _DIMENSIONS
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % _DIMENSIONS
        sign = -1.0 if digest[2] % 2 else 1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]