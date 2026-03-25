from pathlib import Path

from core.intelligence.vector_store import GOEVectorStore


def main():
    store = GOEVectorStore("./data/chromadb")
    store.upsert_document(
        "bootstrap-india-brief",
        "India strategic baseline document for GOE bootstrap.",
        {"domain": "geopolitics", "source_name": "bootstrap"},
    )
    print(f"ChromaDB collection ready with {store.count()} vectors")


if __name__ == "__main__":
    Path("./data/chromadb").mkdir(parents=True, exist_ok=True)
    main()
