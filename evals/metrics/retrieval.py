"""Retrieval ranking metrics — pure functions, no Bedrock or I/O."""

from __future__ import annotations


def precision_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """Fraction of the top-k retrieved items that are in the gold set.

    Returns 0.0 when k <= 0 or retrieved is empty. The denominator is min(k, len(retrieved))
    to avoid penalizing short result lists for being short — a retriever that returned
    fewer than k items still gets credit for the items it did return.
    """
    if k <= 0 or not retrieved:
        return 0.0
    gold_set = set(gold)
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in gold_set)
    return hits / len(top_k)


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """Fraction of the gold items that appear in the top-k retrieved list."""
    if not gold:
        return 0.0
    if k <= 0 or not retrieved:
        return 0.0
    gold_set = set(gold)
    top_k_set = set(retrieved[:k])
    return len(gold_set & top_k_set) / len(gold_set)


def hit_rate_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """1.0 if at least one gold item appears in the top-k, else 0.0."""
    if not gold or k <= 0 or not retrieved:
        return 0.0
    gold_set = set(gold)
    return 1.0 if any(item in gold_set for item in retrieved[:k]) else 0.0


def mean_reciprocal_rank(retrieved: list[str], gold: list[str]) -> float:
    """1 / (rank of first gold hit), or 0 if no gold hit appears.

    For a single query this is the reciprocal rank; the 'mean' applies when
    aggregated across queries by the caller.
    """
    if not gold or not retrieved:
        return 0.0
    gold_set = set(gold)
    for i, item in enumerate(retrieved, start=1):
        if item in gold_set:
            return 1.0 / i
    return 0.0
