"""Shared helpers for the eval runners — agent factory, tool-result extraction,
report writing, cost estimation. No CLI here; that lives in the runner modules.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import AWS_REGION, MAX_TOKENS, MODEL_ID, ORCHESTRATOR_SYSTEM_PROMPT, TEMPERATURE

log = logging.getLogger("eval-runner")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "evals" / "reports"
HISTORY_PATH = REPORTS_DIR / "history.jsonl"
LATEST_PATH = REPORTS_DIR / "latest.md"
GOLDEN_DIR = PROJECT_ROOT / "evals" / "golden"

# Rough cost-per-1k-token estimates (USD, Bedrock on-demand pricing as of 2026).
# Used only for the "estimated cost" line in the report — not an exact bill.
COST_PER_1K_INPUT = {
    "claude-sonnet": 0.003,
    "nova-lite": 0.00006,
    "nova-pro": 0.0008,
}
COST_PER_1K_OUTPUT = {
    "claude-sonnet": 0.015,
    "nova-lite": 0.00024,
    "nova-pro": 0.0032,
}


def build_agent():
    """Build a fresh orchestrator with the same wiring web/server.py uses.

    A fresh agent per case keeps conversation history isolated so test cases
    cannot contaminate each other.
    """
    from strands import Agent
    from strands.models import BedrockModel
    from tools import (
        analyze_document,
        check_eligibility,
        create_action_plan,
        intake_interview,
        search_benefits_kb,
        suggest_followup,
    )

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        streaming=False,
    )
    return Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[
            intake_interview,
            check_eligibility,
            create_action_plan,
            search_benefits_kb,
            analyze_document,
            suggest_followup,
        ],
    )


def extract_tool_results(agent) -> tuple[dict | None, dict | None, list[str]]:
    """Walk agent.messages for tool results.

    Returns (eligibility_data, profile_data, tool_names_called). Mirrors the
    extraction in web/server.py:_extract_tool_results so the eval sees what
    the production WebSocket would see.
    """
    eligibility_data: dict | None = None
    profile_data: dict | None = None
    tool_names: list[str] = []

    messages = getattr(agent, "messages", []) or []
    for msg in messages:
        for block in msg.get("content", []):
            if "toolUse" in block:
                name = block["toolUse"].get("name")
                if name and name not in tool_names:
                    tool_names.append(name)

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            tool_result = block.get("toolResult")
            if not tool_result or tool_result.get("status") != "success":
                continue
            text = ""
            for content_item in tool_result.get("content", []):
                if "text" in content_item:
                    text = content_item["text"]
                    break
            if not text:
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if eligibility_data is None and isinstance(data, dict) and "likely_eligible" in data:
                eligibility_data = data
            if profile_data is None and isinstance(data, dict) and any(
                k in data for k in ("household_size", "annual_income", "state", "employment_status")
            ):
                if "likely_eligible" not in data:
                    profile_data = data
            if eligibility_data is not None and profile_data is not None:
                return eligibility_data, profile_data, tool_names

    return eligibility_data, profile_data, tool_names


def replay_conversation(agent, conversation: list[dict]) -> str:
    """Feed each user turn through the agent in order. Return the final response text.

    Mirrors web/server.py — file references are converted into the same
    bracketed-instruction format the WebSocket layer constructs.
    """
    final_text = ""
    fixtures_dir = GOLDEN_DIR / "fixtures"
    for turn in conversation:
        if turn.get("role") != "user":
            continue
        prompt_parts: list[str] = []
        if turn.get("attached_document"):
            fpath = fixtures_dir / turn["attached_document"]
            if fpath.exists():
                prompt_parts.append(
                    f"[The user uploaded a document: \"{turn['attached_document']}\" "
                    f"(saved at {fpath}). Please use the analyze_document tool to read "
                    f"it and extract relevant information.]"
                )
            else:
                # Fixture missing; tell the agent the document is unreadable so it
                # can degrade gracefully. The runner records a fixture_skipped flag.
                prompt_parts.append(
                    f"[The user attempted to upload \"{turn['attached_document']}\" but "
                    f"the file is unavailable. Please ask the user to provide the "
                    f"information manually instead.]"
                )
        if turn.get("content"):
            prompt_parts.append(turn["content"])
        full_prompt = "\n\n".join(prompt_parts)
        result = agent(full_prompt)
        final_text = str(result)
    return final_text


def model_family_for_cost(model_id: str) -> str:
    mid = model_id.lower()
    if "claude" in mid and "sonnet" in mid:
        return "claude-sonnet"
    if "nova-pro" in mid:
        return "nova-pro"
    return "nova-lite"


def estimate_cost_usd(
    agent_calls: int,
    judge_calls: int,
    avg_in_tokens_per_call: int = 2000,
    avg_out_tokens_per_call: int = 800,
) -> float:
    """Coarse cost estimate. Real bill will differ; this is for the report header."""
    agent_fam = model_family_for_cost(MODEL_ID)
    from config import JUDGE_MODEL_ID
    judge_fam = model_family_for_cost(JUDGE_MODEL_ID)
    agent_cost = agent_calls * (
        avg_in_tokens_per_call / 1000 * COST_PER_1K_INPUT[agent_fam]
        + avg_out_tokens_per_call / 1000 * COST_PER_1K_OUTPUT[agent_fam]
    )
    judge_cost = judge_calls * (
        avg_in_tokens_per_call / 1000 * COST_PER_1K_INPUT[judge_fam]
        + (JUDGE_OUT_TOKENS / 1000) * COST_PER_1K_OUTPUT[judge_fam]
    )
    return round(agent_cost + judge_cost, 4)


JUDGE_OUT_TOKENS = 600  # judges return short JSON; keep separate from agent estimate


def append_history(record: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    record["timestamp"] = _dt.datetime.utcnow().isoformat() + "Z"
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def write_latest_report(content: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LATEST_PATH, "w") as f:
        f.write(content)
