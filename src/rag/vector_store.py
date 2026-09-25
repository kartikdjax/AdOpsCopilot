"""
Vector store for the knowledge base (policies, playbooks, historical
incident notes) - separate ChromaDB collection from any future
per-customer document store, kept isolated for a single-tenant deployment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb
from chromadb.utils import embedding_functions

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk_id: str
    text: str
    source: str
    similarity: float


class KnowledgeBaseStore:
    def __init__(self, settings: Settings, collection_name: str = "knowledge_base") -> None:
        self._client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model_name
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name, embedding_function=embed_fn
        )
        logger.info("KnowledgeBaseStore ready: %d documents indexed", self._collection.count())

    def add(self, ids: list[str], documents: list[str], sources: list[str]) -> None:
        if not ids:
            return
        # upsert, so re-running the seed loader after editing a document
        # updates it instead of failing on (or skipping) existing IDs.
        self._collection.upsert(ids=ids, documents=documents, metadatas=[{"source": s} for s in sources])

    def query(self, query_text: str, n_results: int = 3, min_similarity: float = 0.3) -> list[ScoredChunk]:
        if self._collection.count() == 0:
            return []
        results = self._collection.query(
            query_texts=[query_text], n_results=min(n_results, self._collection.count()),
        )
        scored: list[ScoredChunk] = []
        for doc_id, doc, meta, distance in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            similarity = 1.0 - distance
            if similarity >= min_similarity:
                scored.append(ScoredChunk(chunk_id=doc_id, text=doc,
                                           source=meta.get("source", "unknown"), similarity=similarity))
        return scored

    def document_count(self) -> int:
        return self._collection.count()
