"""Intake tool — gathers citizen profile through conversational interview."""

from __future__ import annotations

import json
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands import Agent, tool
from strands.models import BedrockModel

from config import AWS_REGION, MODEL_ID, MAX_TOKENS, TEMPERATURE, INTAKE_SYSTEM_PROMPT


def _get_intake_model() -> BedrockModel:
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        streaming=False,
    )


@tool
def intake_interview(user_message: str, current_profile: str = "{}") -> str:
    """Conduct a conversational intake interview to build a citizen profile.

    Use this tool to extract structured information from the user's messages.
    Pass in the user's latest message and the current profile JSON (or empty
    JSON {} to start fresh). Returns an updated profile JSON.

    Args:
        user_message: The latest message from the user to extract info from.
        current_profile: The current citizen profile as a JSON string. Defaults to "{}".

    Returns:
        str: Updated citizen profile as a JSON string.
    """
    try:
        existing = json.loads(current_profile)
    except (json.JSONDecodeError, TypeError):
        existing = {}

    prompt = (
        f"Current profile:\n{json.dumps(existing, indent=2)}\n\n"
        f"User said: \"{user_message}\"\n\n"
        "Return the updated profile JSON. Only update fields the user clearly "
        "stated. Keep existing values. Use null for unknown fields. "
        "Return ONLY valid JSON, no markdown fences or extra text."
    )

    try:
        model = _get_intake_model()
        intake_agent = Agent(
            model=model,
            system_prompt=INTAKE_SYSTEM_PROMPT,
        )
        result = intake_agent(prompt)
        response_text = str(result)

        # Try to extract JSON from the response
        # Strip markdown fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        parsed = json.loads(cleaned)
        return json.dumps(parsed, indent=2)

    except json.JSONDecodeError:
        # If the model didn't return valid JSON, merge what we can
        return json.dumps(existing, indent=2)
    except Exception as e:
        return json.dumps({
            "error": f"Intake agent error: {str(e)}",
            "current_profile": existing,
        }, indent=2)
