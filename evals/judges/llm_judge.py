"""Bedrock judge — calls Claude Sonnet, validates against the rubric schema.

One model. One rubric. JSON output. One retry on parse failure. Fail loudly
on the second failure rather than silently degrading the eval signal.
"""

from __future__ import annotations

import json
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import AWS_REGION, JUDGE_MAX_TOKENS, JUDGE_MODEL_ID, JUDGE_TEMPERATURE
from evals.judges.rubric import JudgeVerdict, build_judge_prompt

log = logging.getLogger("eval-judge")

_client = None
_call_count = 0


def get_call_count() -> int:
    """Number of judge invocations since process start. Used by the cost cap."""
    return _call_count


def reset_call_count() -> None:
    global _call_count
    _call_count = 0


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _client


class JudgeAccessError(RuntimeError):
    """Bedrock denied access to the judge model. Surface clearly; do not auto-fallback."""


class JudgeParseError(RuntimeError):
    """The judge returned text we could not parse into a JudgeVerdict, twice."""


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = [l for l in s.split("\n") if not l.strip().startswith("```")]
        s = "\n".join(lines)
    return s.strip()


def _invoke_bedrock(prompt: str) -> str:
    client = _get_client()
    try:
        response = client.converse(
            modelId=JUDGE_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": JUDGE_MAX_TOKENS,
                "temperature": JUDGE_TEMPERATURE,
            },
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = str(e)
        # Both AccessDenied and the Anthropic-specific "use case details have not
        # been submitted" ResourceNotFoundException are operator setup issues:
        # surface them loudly so the user fixes them, not silent per-case retries.
        if (
            "AccessDenied" in code
            or "AccessDeniedException" in code
            or ("ResourceNotFound" in code and "use case" in msg.lower())
        ):
            raise JudgeAccessError(
                f"Bedrock cannot invoke judge model {JUDGE_MODEL_ID!r}: {msg}\n\n"
                f"Action required (do this in the AWS console, not in code):\n"
                f"  1. Bedrock console → Model access — confirm Claude Sonnet is enabled in {AWS_REGION}.\n"
                f"  2. If the message mentions 'Anthropic use case details', complete the\n"
                f"     Anthropic use-case form for this account.\n"
                f"  3. Re-run after the form is approved.\n"
                f"Do NOT change JUDGE_MODEL_ID to a Nova model — same-family judging\n"
                f"defeats the methodological purpose. See evals/README.md."
            ) from e
        raise

    content = response["output"]["message"]["content"]
    return " ".join(block.get("text", "") for block in content)


def judge_response(
    conversation: list[dict],
    expectations: dict,
    agent_response: str,
) -> JudgeVerdict:
    """Score one (conversation, expectation, response) triple.

    Returns a validated JudgeVerdict. Raises JudgeAccessError on Bedrock access
    failures (loudly — see config docstring for why). Raises JudgeParseError if
    the model returns unparseable JSON twice in a row.
    """
    global _call_count
    prompt = build_judge_prompt(conversation, expectations, agent_response)

    last_error: Exception | None = None
    for attempt in (1, 2):
        _call_count += 1
        raw = _invoke_bedrock(prompt)
        cleaned = _strip_json_fences(raw)
        try:
            data = json.loads(cleaned)
            verdict = JudgeVerdict(**data)
            return verdict.recompute_pass()
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            log.warning("Judge parse failure on attempt %d: %s\nRaw output: %s", attempt, e, raw[:500])
            continue

    raise JudgeParseError(
        f"Judge model {JUDGE_MODEL_ID!r} returned unparseable output twice. "
        f"Last error: {last_error}"
    )
