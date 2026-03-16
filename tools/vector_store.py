"""In-memory vector store using Nova Multimodal Embedding.

On first use, loads program descriptions and FAQ chunks from data/,
generates embeddings via Nova Embed, and stores them in a plain Python list.
Semantic search uses cosine similarity — no external vector DB needed.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("benefits-vectorstore")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# In-memory store: list of {"text": str, "embedding": list[float], "metadata": dict}
_store: list[dict] = []
_initialized = False


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _load_chunks() -> list[dict]:
    """Load all text chunks from data/ JSON files for embedding."""
    chunks: list[dict] = []

    # Load detailed program content
    details_path = _DATA_DIR / "program_details.json"
    if details_path.exists():
        with open(details_path) as f:
            programs = json.load(f)
        for prog in programs:
            pid = prog.get("program_id", "unknown")
            for chunk in prog.get("chunks", []):
                chunks.append({
                    "text": f"{chunk['title']}: {chunk['text']}",
                    "metadata": {
                        "program_id": pid,
                        "title": chunk["title"],
                        "source": "program_details",
                    },
                })

    # Load federal program summaries
    fed_path = _DATA_DIR / "federal_programs.json"
    if fed_path.exists():
        with open(fed_path) as f:
            federal = json.load(f)
        for prog in federal:
            text = (
                f"{prog['name']} ({prog.get('short_name', '')}): "
                f"{prog.get('description', '')} "
                f"Category: {prog.get('category', '')}. "
                f"Estimated benefit: {prog.get('estimated_benefit', '')}."
            )
            chunks.append({
                "text": text,
                "metadata": {
                    "program_id": prog["id"],
                    "title": prog["name"],
                    "source": "federal_programs",
                    "category": prog.get("category", ""),
                    "application_url": prog.get("application_url", ""),
                },
            })

    # Load state program summaries
    state_path = _DATA_DIR / "state_programs.json"
    if state_path.exists():
        with open(state_path) as f:
            state_data = json.load(f)
        for state_code, programs in state_data.items():
            for prog in programs:
                text = (
                    f"{prog['name']} ({prog.get('short_name', '')}): "
                    f"{prog.get('description', '')} "
                    f"State: {state_code}. Category: {prog.get('category', '')}. "
                    f"Estimated benefit: {prog.get('estimated_benefit', '')}."
                )
                chunks.append({
                    "text": text,
                    "metadata": {
                        "program_id": prog["id"],
                        "title": prog["name"],
                        "source": "state_programs",
                        "state": state_code,
                        "category": prog.get("category", ""),
                        "application_url": prog.get("application_url", ""),
                    },
                })

    return chunks


def initialize():
    """Load chunks and generate embeddings. Call once on startup."""
    global _store, _initialized

    if _initialized:
        return

    from tools.embeddings import generate_embedding

    chunks = _load_chunks()
    log.info("Generating embeddings for %d knowledge base chunks...", len(chunks))

    for i, chunk in enumerate(chunks):
        try:
            embedding = generate_embedding(chunk["text"][:2000])  # truncate for safety
            _store.append({
                "text": chunk["text"],
                "embedding": embedding,
                "metadata": chunk["metadata"],
            })
        except Exception as e:
            log.warning("Failed to embed chunk %d (%s): %s", i, chunk["metadata"].get("title", "?"), e)

    _initialized = True
    log.info("Vector store initialized with %d embeddings.", len(_store))


def is_initialized() -> bool:
    return _initialized


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Search the vector store for chunks most relevant to the query.

    Args:
        query: Natural language search query.
        top_k: Number of results to return.

    Returns:
        List of dicts with keys: text, score, metadata.
    """
    if not _store:
        # If embeddings aren't loaded, fall back gracefully
        return []

    from tools.embeddings import generate_embedding

    query_embedding = generate_embedding(query)

    scored = []
    for entry in _store:
        score = _cosine_similarity(query_embedding, entry["embedding"])
        scored.append({
            "text": entry["text"],
            "score": score,
            "metadata": entry["metadata"],
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
