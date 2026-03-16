"""Benefits knowledge base search tool — semantic search via Nova Embedding with keyword fallback."""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import tool

log = logging.getLogger("benefits-kb")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Category aliases for keyword fallback
_CATEGORY_KEYWORDS = {
    "food": ["food", "grocery", "groceries", "eat", "hunger", "snap", "ebt", "calfresh", "wic", "nutrition"],
    "healthcare": ["health", "medical", "doctor", "hospital", "insurance", "medicaid", "medi-cal", "chip"],
    "housing": ["housing", "rent", "shelter", "section 8", "voucher", "homeless", "apartment"],
    "utilities": ["utility", "utilities", "energy", "electric", "gas", "heating", "cooling", "phone", "internet", "bill"],
    "cash_assistance": ["cash", "money", "tanf", "calworks", "ssi", "welfare", "capi"],
    "tax_credit": ["tax", "eitc", "earned income", "child tax credit", "refund", "credit"],
    "education": ["education", "college", "school", "pell", "grant", "tuition", "student", "fafsa"],
}


def _keyword_match_score(query: str, program: dict) -> int:
    """Score how well a program matches a search query using keyword matching."""
    query_lower = query.lower()
    score = 0
    name = program.get("name", "").lower()
    short = program.get("short_name", "").lower()
    desc = program.get("description", "").lower()

    for word in query_lower.split():
        if word in name:
            score += 3
        if word in short:
            score += 3
        if word in desc:
            score += 1

    category = program.get("category", "")
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            if category == cat:
                score += 5
    return score


def _keyword_search(query: str, state: str) -> list[dict]:
    """Fallback keyword search when embeddings are unavailable."""
    programs: list[dict] = []

    fed_path = os.path.join(_DATA_DIR, "federal_programs.json")
    with open(fed_path) as f:
        programs.extend(json.load(f))

    state_path = os.path.join(_DATA_DIR, "state_programs.json")
    with open(state_path) as f:
        state_data = json.load(f)
    programs.extend(state_data.get(state.upper(), []))

    scored = [(s, p) for p in programs if (s := _keyword_match_score(query, p)) > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for _, prog in scored[:8]:
        results.append({
            "name": prog["name"],
            "short_name": prog.get("short_name", prog["name"]),
            "category": prog.get("category", ""),
            "description": prog.get("description", ""),
            "income_limit_fpl_pct": prog.get("income_limit_fpl_pct"),
            "estimated_benefit": prog.get("estimated_benefit", "varies"),
            "application_url": prog.get("application_url", ""),
            "application_methods": prog.get("application_methods", []),
        })
    return results


@tool
def search_benefits_kb(query: str, state: str = "CA") -> str:
    """Search the benefits knowledge base for programs matching a query.

    Uses Nova Multimodal Embedding for semantic search — understands meaning,
    not just keywords. For example, 'help buying groceries' matches SNAP even
    though the word 'groceries' may not appear in the program description.

    Falls back to keyword matching if embeddings are unavailable.

    Args:
        query: Natural language search query (e.g., 'food assistance', 'help with rent').
        state: Two-letter state code to include state programs. Defaults to 'CA'.

    Returns:
        str: JSON with matching programs, descriptions, and application tips.
    """
    # Try semantic search first
    try:
        from tools.vector_store import is_initialized, semantic_search, initialize

        if not is_initialized():
            initialize()

        if is_initialized():
            hits = semantic_search(query, top_k=6)

            if hits:
                results = []
                seen_programs = set()

                for hit in hits:
                    pid = hit["metadata"].get("program_id", "")
                    title = hit["metadata"].get("title", "")
                    key = f"{pid}:{title}"

                    if key in seen_programs:
                        continue
                    seen_programs.add(key)

                    results.append({
                        "program_id": pid,
                        "title": title,
                        "text": hit["text"],
                        "relevance_score": round(hit["score"], 3),
                        "source": hit["metadata"].get("source", ""),
                        "category": hit["metadata"].get("category", ""),
                        "application_url": hit["metadata"].get("application_url", ""),
                    })

                log.info("Semantic search for '%s' returned %d results", query, len(results))
                return json.dumps({
                    "search_method": "semantic (Nova Multimodal Embedding)",
                    "results": results,
                }, indent=2)

    except Exception as e:
        log.warning("Semantic search failed, falling back to keywords: %s", e)

    # Fallback to keyword search
    results = _keyword_search(query, state)

    if not results:
        return json.dumps({
            "search_method": "keyword (fallback)",
            "message": "No programs found matching your query. Try broader terms like 'food', 'healthcare', 'housing', or 'cash assistance'.",
            "results": [],
        })

    return json.dumps({
        "search_method": "keyword (fallback)",
        "results": results,
    }, indent=2)
