"""Action Plan tool — generates a prioritized step-by-step plan with cross-program optimization."""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import Agent, tool
from strands.models import BedrockModel

from config import (
    AWS_REGION,
    MODEL_ID,
    MAX_TOKENS,
    TEMPERATURE,
    ACTION_PLAN_SYSTEM_PROMPT,
)
from tools.cross_program import get_cross_program_insights


def _get_plan_model() -> BedrockModel:
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        streaming=False,
    )


@tool
def create_action_plan(citizen_profile: str, eligible_programs: str) -> str:
    """Generate a personalized, prioritized action plan for applying to benefits.

    Takes the citizen profile and eligibility results, then creates a concrete
    step-by-step plan organized by priority. Includes cross-program optimization
    insights — strategic ordering of applications, dependency chains between
    programs, time-sensitive deadlines, and efficiency tips.

    Args:
        citizen_profile: Citizen profile as a JSON string.
        eligible_programs: Eligibility results JSON from check_eligibility.

    Returns:
        str: A detailed, prioritized action plan as formatted text.
    """
    try:
        profile = json.loads(citizen_profile)
        programs = json.loads(eligible_programs)
    except (json.JSONDecodeError, TypeError) as e:
        return f"Error parsing input: {e}"

    # Gather cross-program insights
    eligible_list = []
    for key in ("likely_eligible", "possibly_eligible"):
        eligible_list.extend(programs.get(key, []))

    insights = get_cross_program_insights(profile, eligible_list)

    # Format insights for the LLM
    insights_text = ""
    if insights:
        insights_text = "\n\nCROSS-PROGRAM STRATEGIC INSIGHTS (incorporate these into the plan):\n"
        for i, ins in enumerate(insights, 1):
            insights_text += (
                f"\n{i}. [{ins['type'].upper()}] {ins['title']}\n"
                f"   {ins['detail']}\n"
                f"   Programs: {', '.join(ins['programs'])}\n"
            )

    prompt = (
        f"Citizen profile:\n{json.dumps(profile, indent=2)}\n\n"
        f"Eligible programs:\n{json.dumps(programs, indent=2)}\n"
        f"{insights_text}\n\n"
        "Create a prioritized, step-by-step action plan. Group into:\n"
        "1. Immediate Actions (crisis needs — food, shelter, healthcare)\n"
        "2. High Priority (highest benefit, easiest to apply)\n"
        "3. Medium Priority (other worthwhile programs)\n"
        "4. Tax-Time Actions (EITC, Child Tax Credit, etc.)\n\n"
        "IMPORTANT: Use the cross-program strategic insights above to determine "
        "the optimal ORDER of applications. Explain WHY you're recommending a "
        "specific order (e.g., 'Apply for Medi-Cal first because approval "
        "streamlines your CalFresh application'). Highlight time-sensitive "
        "actions and efficiency tips.\n\n"
        "For each program include: how to apply, required documents, "
        "processing time, application URL, and tips.\n\n"
        "Use encouraging, non-judgmental language. Remind the user that "
        "this is informational guidance and final eligibility is determined "
        "by the administering agency."
    )

    try:
        model = _get_plan_model()
        plan_agent = Agent(
            model=model,
            system_prompt=ACTION_PLAN_SYSTEM_PROMPT,
        )
        result = plan_agent(prompt)
        return str(result)
    except Exception as e:
        return f"Action plan generation error: {e}"
