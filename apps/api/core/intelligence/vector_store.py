"""
ChromaDB wrapper with an in-memory fallback.
Exposes the v4.1 query/upsert/is_duplicate interface while staying import-safe
when optional dependencies are not installed in the local environment.
"""
from __future__ import annotations

import math
from pathlib import Path

from .embedder import embed

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
except Exception:
    chromadb = None
    ChromaSettings = None


class GOEVectorStore:
    def __init__(self, persist_dir: str = "./data/chromadb"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection = None
        self._memory: dict[str, dict] = {}

        if chromadb is not None:
            self.client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self.collection = self.client.get_or_create_collection(
                name="goe_intelligence",
                metadata={"hnsw:space": "cosine"},
            )
        else:
            self.client = None

    def upsert(self, signal_id: str, text: str, metadata: dict):
        clean_meta = _clean_metadata(metadata)
        vector = embed(text or "")
        document = (text or "")[:1000]
        if self.collection is not None:
            self.collection.upsert(
                ids=[signal_id],
                embeddings=[vector],
                documents=[document],
                metadatas=[clean_meta],
            )
        else:
            self._memory[signal_id] = {
                "id": signal_id,
                "document": document,
                "metadata": clean_meta,
                "embedding": vector,
            }
        return signal_id

    def upsert_document(self, document_id: str, text: str, metadata: dict | None = None):
        return self.upsert(document_id, text, metadata or {})

    def query(self, query_text: str, n_results: int = 10, where: dict | None = None) -> list[dict]:
        if self.count() == 0:
            return []

        if self.collection is not None:
            kwargs = {
                "query_embeddings": [embed(query_text or "")],
                "n_results": min(n_results, self.collection.count() or 1),
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where
            try:
                results = self.collection.query(**kwargs)
                items = []
                for index in range(len(results["ids"][0])):
                    distance = float(results["distances"][0][index])
                    items.append(
                        {
                            "id": results["ids"][0][index],
                            "document": results["documents"][0][index],
                            "metadata": results["metadatas"][0][index],
                            "distance": distance,
                            "score": 1 - distance,
                        }
                    )
                return items
            except Exception:
                return []

        query_vector = embed(query_text or "")
        matches = []
        for item in self._memory.values():
            if where and any(item["metadata"].get(key) != value for key, value in where.items()):
                continue
            score = _cosine_similarity(query_vector, item["embedding"])
            matches.append(
                {
                    "id": item["id"],
                    "document": item["document"],
                    "metadata": item["metadata"],
                    "distance": 1 - score,
                    "score": score,
                }
            )
        matches.sort(key=lambda match: match["score"], reverse=True)
        return matches[:n_results]

    def similarity_search(self, query_text: str, limit: int = 10, where: dict | None = None) -> list[dict]:
        results = self.query(query_text, n_results=limit, where=where)
        return [
            {
                "id": item["id"],
                "text": item["document"],
                "metadata": item["metadata"],
                "score": item["score"],
            }
            for item in results
        ]

    def is_duplicate(self, text: str, threshold: float = 0.97) -> bool:
        if self.count() == 0:
            return False
        results = self.query(text, n_results=1)
        return bool(results and results[0]["score"] >= threshold)

    def count(self) -> int:
        if self.collection is not None:
            return self.collection.count()
        return len(self._memory)

    def delete(self, signal_id: str):
        if self.collection is not None:
            self.collection.delete(ids=[signal_id])
        else:
            self._memory.pop(signal_id, None)


def _clean_metadata(metadata: dict | None) -> dict:
    clean = {}
    for key, value in (metadata or {}).items():
        if value is None:
            clean[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return numerator / (left_norm * right_norm)