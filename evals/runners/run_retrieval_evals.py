"""Run retrieval evals over the 51-chunk KB.

For each query in evals/golden/retrieval.json:
  1. Initialize the vector store (lazy-embed on first run, cached after).
  2. Call semantic_search(query, top_k=5).
  3. Compute P@1 / P@3 / P@5, R@5, MRR, hit_rate@5 against gold_chunk_ids.

Aggregate, write to history.jsonl, append a section to latest.md (or write a
standalone retrieval-only report when invoked directly).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import MODEL_ID
from evals.metrics.retrieval import (
    hit_rate_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)
from evals.runners._common import GOLDEN_DIR, append_history

log = logging.getLogger("retrieval-eval")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

TOP_K = 5


def _retrieve(query: str) -> list[str]:
    """Return list of chunk_ids for the top-K retrieved chunks."""
    from tools.vector_store import initialize, is_initialized, semantic_search
    if not is_initialized():
        initialize()
    hits = semantic_search(query, top_k=TOP_K)
    return [h["metadata"]["chunk_id"] for h in hits]


def run_one(case: dict) -> dict:
    query = case["query"]
    gold = case["gold_chunk_ids"]
    retrieved = _retrieve(query)
    return {
        "id": case["id"],
        "category": case.get("category"),
        "query": query,
        "gold": gold,
        "retrieved": retrieved,
        "p_at_1": precision_at_k(retrieved, gold, 1),
        "p_at_3": precision_at_k(retrieved, gold, 3),
        "p_at_5": precision_at_k(retrieved, gold, 5),
        "r_at_5": recall_at_k(retrieved, gold, 5),
        "mrr": mean_reciprocal_rank(retrieved, gold),
        "hit_at_5": hit_rate_at_k(retrieved, gold, 5),
    }


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {"total": 0}
    return {
        "total": n,
        "p_at_1": sum(r["p_at_1"] for r in results) / n,
        "p_at_3": sum(r["p_at_3"] for r in results) / n,
        "p_at_5": sum(r["p_at_5"] for r in results) / n,
        "r_at_5": sum(r["r_at_5"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
        "hit_at_5": sum(r["hit_at_5"] for r in results) / n,
    }


def render_section(results: list[dict], agg: dict) -> str:
    lines = ["## Retrieval evals"]
    lines.append(f"- Total queries: {agg['total']}")
    lines.append(f"- P@1: {agg['p_at_1']:.2f} | P@3: {agg['p_at_3']:.2f} | P@5: {agg['p_at_5']:.2f}")
    lines.append(f"- R@5: {agg['r_at_5']:.2f}")
    lines.append(f"- MRR: {agg['mrr']:.2f}")
    lines.append(f"- Hit rate @5: {agg['hit_at_5']:.2f}")
    lines.append("")

    worst = sorted(results, key=lambda r: (r["hit_at_5"], r["mrr"], r["p_at_5"]))[:5]
    if worst:
        lines.append("### Worst queries")
        for r in worst:
            if r["hit_at_5"] >= 1.0 and r["p_at_5"] >= 0.5:
                continue
            missing = [g for g in r["gold"] if g not in r["retrieved"]]
            lines.append(
                f"- **{r['id']}** ({r['category']}, P@5={r['p_at_5']:.2f}, MRR={r['mrr']:.2f}): "
                f"{r['query']!r}"
            )
            if missing:
                lines.append(f"    missing gold chunks: {missing}")
            lines.append(f"    retrieved: {r['retrieved']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-json", type=str, default=None)
    args = parser.parse_args()

    with open(GOLDEN_DIR / "retrieval.json") as f:
        cases = json.load(f)
    log.info("Loaded %d retrieval queries", len(cases))

    results = [run_one(c) for c in cases]
    agg = aggregate(results)
    section = render_section(results, agg)
    print(section)

    append_history({
        "kind": "retrieval_evals",
        "agent_model": MODEL_ID,
        "total_queries": agg["total"],
        **{k: agg[k] for k in ("p_at_1", "p_at_3", "p_at_5", "r_at_5", "mrr", "hit_at_5")},
    })

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump({"aggregate": agg, "results": results}, f, indent=2)


if __name__ == "__main__":
    main()
