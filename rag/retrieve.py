"""Vector search over the chunks written by rag.ingest."""
from __future__ import annotations

import json
from functools import cached_property

from rag import config


class Retriever:
    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(config.EMBED_MODEL)

    @cached_property
    def index(self):
        import faiss
        path = config.INDEX_DIR / "chunks.faiss"
        if not path.exists():
            raise SystemExit("index/ is empty; run `python -m rag.ingest` first")
        return faiss.read_index(str(path))

    @cached_property
    def chunks(self) -> list[dict]:
        with (config.INDEX_DIR / "chunks.jsonl").open(encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def search(self, question: str, k: int = 5) -> list[dict]:
        q = self.model.encode([f"query: {question}"], normalize_embeddings=True)
        scores, ids = self.index.search(q, k)
        return [{**self.chunks[i], "score": float(s)} for s, i in zip(scores[0], ids[0]) if i >= 0]
