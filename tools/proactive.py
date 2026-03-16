"""Proactive follow-up tool — identifies profile gaps and suggests targeted questions."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import tool

from tools.cross_program import get_profile_gaps


@tool
def suggest_followup(citizen_profile: str, eligible_programs: str) -> str:
    """Analyze the citizen profile for gaps that could unlock additional benefits.

    After presenting initial eligibility results, use this tool to identify
    missing profile fields and generate targeted follow-up questions. This
    enables proactive, agent-driven discovery of additional programs.

    Args:
        citizen_profile: Current citizen profile as a JSON string.
        eligible_programs: Current eligibility results JSON from check_eligibility.

    Returns:
        str: JSON with missing fields and suggested follow-up questions.
    """
    try:
        profile = json.loads(citizen_profile)
    except (json.JSONDecodeError, TypeError):
        profile = {}

    try:
        programs_data = json.loads(eligible_programs)
    except (json.JSONDecodeError, TypeError):
        programs_data = {}

    # Flatten eligible programs into a list
    eligible = []
    for key in ("likely_eligible", "possibly_eligible"):
        eligible.extend(programs_data.get(key, []))

    gaps = get_profile_gaps(profile, eligible)

    if not gaps:
        return json.dumps({
            "has_gaps": False,
            "message": "Profile is comprehensive — no additional questions needed.",
            "gaps": [],
        }, indent=2)

    # Limit to top 3 most impactful gaps
    top_gaps = gaps[:3]

    return json.dumps({
        "has_gaps": True,
        "num_gaps": len(gaps),
        "gaps": [
            {
                "field": g["field"],
                "question": g["question"],
                "reason": g["reason"],
                "potential_programs": g["potential_programs"],
            }
            for g in top_gaps
        ],
        "message": (
            f"I found {len(gaps)} pieces of information that could unlock "
            f"additional benefits. Here are the most important ones to ask about."
        ),
    }, indent=2)
