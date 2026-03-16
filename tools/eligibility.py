"""Eligibility tool — matches a citizen profile against all known programs."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import tool

from tools.rules_engine import check_program_eligibility

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _load_programs(state: str | None = None) -> list[dict]:
    """Load federal and applicable state programs."""
    programs: list[dict] = []

    fed_path = os.path.join(_DATA_DIR, "federal_programs.json")
    with open(fed_path, "r") as f:
        programs.extend(json.load(f))

    if state:
        state_path = os.path.join(_DATA_DIR, "state_programs.json")
        with open(state_path, "r") as f:
            state_data = json.load(f)
        state_programs = state_data.get(state.upper(), [])
        programs.extend(state_programs)

    return programs


@tool
def check_eligibility(citizen_profile: str) -> str:
    """Evaluate a citizen's eligibility for all known benefit programs.

    Takes a citizen profile JSON and runs it through the deterministic rules
    engine against all federal and applicable state programs. Returns results
    grouped by likelihood: likely_eligible, possibly_eligible, not_eligible.

    Args:
        citizen_profile: Citizen profile as a JSON string with fields like
            state, household_size, annual_income, employment_status, etc.

    Returns:
        str: JSON summary of eligibility results grouped by likelihood.
    """
    try:
        profile = json.loads(citizen_profile)
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid profile JSON"})

    state = profile.get("state")
    programs = _load_programs(state)

    likely: list[dict] = []
    possibly: list[dict] = []
    not_eligible: list[dict] = []

    for program in programs:
        result = check_program_eligibility(profile, program)
        entry = {
            "program_name": program["name"],
            "short_name": program.get("short_name", program["name"]),
            "category": program.get("category", "other"),
            "confidence": result["confidence"],
            "reason": result["reason"],
            "estimated_benefit": result["estimated_benefit"],
            "application_url": program.get("application_url", ""),
            "processing_time_days": program.get("processing_time_days"),
        }

        if result["eligible"] and result["confidence"] == "high":
            likely.append(entry)
        elif result["eligible"]:
            possibly.append(entry)
        else:
            not_eligible.append(entry)

    return json.dumps({
        "likely_eligible": likely,
        "possibly_eligible": possibly,
        "not_eligible": not_eligible,
        "total_programs_checked": len(programs),
    }, indent=2)
