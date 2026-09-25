"""
Run once to populate the knowledge base with seed documents so
search_knowledge_base has something to find before you've added your
own real policy/playbook docs.

Run: python -m src.rag.load_seed_documents
"""
from __future__ import annotations

import logging

from src.config import get_settings
from src.rag.chunking import recursive_chunk
from src.rag.seed_documents import SEED_DOCUMENTS
from src.rag.vector_store import KnowledgeBaseStore

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    store = KnowledgeBaseStore(settings)

    chunk_ids, chunk_texts, chunk_sources = [], [], []
    for doc_index, doc in enumerate(SEED_DOCUMENTS):
        for chunk in recursive_chunk(doc["text"], max_chunk_size=500):
            chunk_ids.append(f"{doc['source']}_{doc_index}_{chunk.chunk_index}")
            chunk_texts.append(chunk.text)
            chunk_sources.append(doc["source"])

    store.add(ids=chunk_ids, documents=chunk_texts, sources=chunk_sources)
    logger.info("Loaded %d documents -> %d chunks. Total in knowledge base: %d",
                len(SEED_DOCUMENTS), len(chunk_ids), store.document_count())


if __name__ == "__main__":
    main()
