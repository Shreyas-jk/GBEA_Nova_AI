"""Replay golden conversations through the orchestrator and grade them.

Each case is run through:
  1. A fresh agent (per-case isolation).
  2. The user turns are replayed in order.
  3. Deterministic safety/format checks run on the final response.
  4. Set-based comparisons against extracted_profile and eligible_programs.
  5. The LLM judge scores the response on the rubric.
  6. The case passes only if (a) deterministic checks all pass, (b) judge
     overall_pass is true, and (c) eligibility set inclusions/exclusions hold.

Aggregate output: pass rate, mean score per dimension, list of failing IDs.
Run is appended to history.jsonl and overwrites latest.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import JUDGE_MODEL_ID, MODEL_ID
from evals.judges.llm_judge import (
    JudgeAccessError,
    JudgeParseError,
    get_call_count as judge_call_count,
    judge_response,
    reset_call_count as reset_judge_calls,
)
from evals.judges.rubric import DIMENSIONS
from evals.metrics.safety import (
    asks_for_bank_info,
    asks_for_password,
    asks_for_ssn,
    contains_any,
    contains_none,
    includes_crisis_resource,
    uses_definitive_qualification,
)
from evals.runners._common import (
    GOLDEN_DIR,
    append_history,
    build_agent,
    estimate_cost_usd,
    extract_tool_results,
    replay_conversation,
    write_latest_report,
)

log = logging.getLogger("conv-eval")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _load_cases(subset: str | None) -> list[dict]:
    with open(GOLDEN_DIR / "conversations.json") as f:
        cases = json.load(f)
    if subset == "smoke":
        cases = [c for c in cases if c.get("smoke") is True]
    return cases


def _run_deterministic_checks(response: str, expectations: dict) -> dict:
    """Return {check_name: {passed: bool, detail: str}}."""
    checks: dict[str, dict] = {}

    must_not_request = expectations.get("must_not_request", [])
    if any(t in must_not_request for t in ("ssn", "social security number")):
        checks["does_not_ask_for_ssn"] = {"passed": not asks_for_ssn(response), "detail": ""}
    if "bank account" in must_not_request:
        checks["does_not_ask_for_bank_info"] = {"passed": not asks_for_bank_info(response), "detail": ""}
    if "password" in must_not_request:
        checks["does_not_ask_for_password"] = {"passed": not asks_for_password(response), "detail": ""}

    if expectations.get("must_use_hedged_language"):
        unhedged = uses_definitive_qualification(response)
        checks["uses_hedged_language"] = {
            "passed": not unhedged,
            "detail": "Definitive 'you qualify' detected" if unhedged else "",
        }

    crisis_required = expectations.get("must_contain_resource_phone")
    if crisis_required:
        present = includes_crisis_resource(response, crisis_required)
        checks["crisis_resources_present"] = {
            "passed": present,
            "detail": f"Required: {crisis_required}" if not present else "",
        }

    must_any = expectations.get("must_contain_phrases_any")
    if must_any:
        ok = contains_any(response, must_any)
        checks["contains_any_required_phrase"] = {
            "passed": ok,
            "detail": f"None of {must_any} found" if not ok else "",
        }

    must_any_alt = expectations.get("must_contain_phrases_any_alt")
    if must_any_alt:
        ok = contains_any(response, must_any_alt)
        checks["contains_any_alt_phrase"] = {
            "passed": ok,
            "detail": f"None of {must_any_alt} found" if not ok else "",
        }

    must_not = expectations.get("must_not_contain_phrases")
    if must_not:
        ok = contains_none(response, must_not)
        checks["does_not_contain_forbidden_phrase"] = {
            "passed": ok,
            "detail": f"Forbidden phrase appeared (one of {must_not})" if not ok else "",
        }

    min_len = expectations.get("min_response_length_chars")
    if min_len:
        checks["meets_min_response_length"] = {
            "passed": len(response) >= min_len,
            "detail": f"len={len(response)} < {min_len}" if len(response) < min_len else "",
        }

    return checks


def _check_extracted_profile(profile_data: dict | None, expectations: dict) -> dict | None:
    """Compare what the agent extracted against expected fields. None if no expectation."""
    expected = expectations.get("extracted_profile")
    if not expected:
        return None
    if profile_data is None:
        return {"passed": False, "detail": "Agent did not produce a structured profile"}
    mismatches = []
    for key, want in expected.items():
        got = profile_data.get(key)
        if got != want:
            mismatches.append(f"{key}: expected {want!r}, got {got!r}")
    return {
        "passed": not mismatches,
        "detail": "; ".join(mismatches) if mismatches else "",
    }


def _eligible_set(eligibility_data: dict | None) -> set[str]:
    """Flatten likely+possibly into a lowercase short_name set."""
    if not eligibility_data:
        return set()
    names: set[str] = set()
    for key in ("likely_eligible", "possibly_eligible"):
        for entry in eligibility_data.get(key, []):
            names.add((entry.get("short_name") or entry.get("program_name") or "").lower())
    return names


def _check_eligibility_membership(
    eligibility_data: dict | None, expectations: dict
) -> dict | None:
    must_include = expectations.get("eligible_programs_must_include")
    must_exclude = expectations.get("eligible_programs_must_exclude")
    if not must_include and not must_exclude:
        return None
    if eligibility_data is None:
        return {
            "passed": False,
            "detail": "Agent never produced an eligibility result via check_eligibility",
        }
    eligible = _eligible_set(eligibility_data)
    missing_includes = [p for p in (must_include or []) if p.lower() not in eligible]
    leaked_excludes = [p for p in (must_exclude or []) if p.lower() in eligible]
    detail_parts = []
    if missing_includes:
        detail_parts.append(f"missing required programs: {missing_includes}")
    if leaked_excludes:
        detail_parts.append(f"included programs that should be excluded: {leaked_excludes}")
    return {
        "passed": not (missing_includes or leaked_excludes),
        "detail": "; ".join(detail_parts) if detail_parts else "",
    }


def _check_required_tools(tools_called: list[str], expectations: dict) -> dict | None:
    must_call = expectations.get("must_call_tool")
    if not must_call:
        return None
    missing = [t for t in must_call if t not in tools_called]
    return {
        "passed": not missing,
        "detail": f"Did not call required tools: {missing}" if missing else "",
    }


def run_one_case(case: dict, cost_cap: int | None = None) -> dict:
    """Execute one conversation case, return a result dict."""
    case_id = case["id"]
    log.info("Running case %s (%s)", case_id, case["category"])
    expectations = case.get("expectations", {})

    result: dict[str, Any] = {
        "id": case_id,
        "category": case["category"],
        "smoke": case.get("smoke", False),
        "agent_calls": 0,
        "judge_calls": 0,
    }

    try:
        agent = build_agent()
    except Exception as e:
        result["error"] = f"agent_build_failed: {e}"
        result["passed"] = False
        return result

    try:
        agent_call_count_before = len(case["conversation"])
        response = replay_conversation(agent, case["conversation"])
        result["agent_calls"] = agent_call_count_before
        result["response"] = response
    except Exception as e:
        log.warning("Case %s agent call failed: %s", case_id, e)
        result["error"] = f"agent_invocation_failed: {e}"
        result["passed"] = False
        return result

    eligibility_data, profile_data, tools_called = extract_tool_results(agent)
    result["tools_called"] = tools_called

    deterministic = _run_deterministic_checks(response, expectations)
    profile_check = _check_extracted_profile(profile_data, expectations)
    eligibility_check = _check_eligibility_membership(eligibility_data, expectations)
    tool_check = _check_required_tools(tools_called, expectations)

    result["deterministic_checks"] = deterministic
    if profile_check is not None:
        result["profile_check"] = profile_check
    if eligibility_check is not None:
        result["eligibility_check"] = eligibility_check
    if tool_check is not None:
        result["tool_check"] = tool_check

    deterministic_pass = all(c["passed"] for c in deterministic.values())
    profile_pass = profile_check is None or profile_check["passed"]
    eligibility_pass = eligibility_check is None or eligibility_check["passed"]
    tool_pass = tool_check is None or tool_check["passed"]

    # Run judge unless we're at the cost cap
    judge_verdict = None
    if cost_cap is not None and judge_call_count() >= cost_cap:
        log.warning("Cost cap reached (%d judge calls); skipping judge for %s", cost_cap, case_id)
        result["judge_skipped_cost_cap"] = True
    else:
        try:
            calls_before = judge_call_count()
            judge_verdict = judge_response(case["conversation"], expectations, response)
            result["judge_calls"] = judge_call_count() - calls_before
            result["judge_scores"] = judge_verdict.scores.model_dump()
            result["judge_justifications"] = judge_verdict.justifications
            result["judge_overall_pass"] = judge_verdict.overall_pass
        except JudgeAccessError as e:
            # Loud failure — do not silently degrade
            raise
        except JudgeParseError as e:
            log.warning("Case %s judge parse failure: %s", case_id, e)
            result["judge_error"] = str(e)
            result["judge_overall_pass"] = False

    judge_pass = judge_verdict.overall_pass if judge_verdict is not None else False
    result["passed"] = bool(
        deterministic_pass and profile_pass and eligibility_pass and tool_pass and judge_pass
    )
    return result


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    by_dim = {dim: [] for dim in DIMENSIONS}
    for r in results:
        scores = r.get("judge_scores")
        if scores:
            for dim in DIMENSIONS:
                by_dim[dim].append(scores[dim])
    means = {dim: (sum(v) / len(v) if v else None) for dim, v in by_dim.items()}
    failing = [r["id"] for r in results if not r.get("passed")]
    return {
        "total": n,
        "passed": passed,
        "pass_rate": passed / n if n else 0.0,
        "mean_scores": means,
        "failing_ids": failing,
    }


def render_section(results: list[dict], agg: dict) -> str:
    lines = ["## Conversation evals"]
    lines.append(f"- Total cases: {agg['total']}")
    lines.append(f"- Pass rate: {agg['passed']}/{agg['total']} ({agg['pass_rate'] * 100:.1f}%)")
    for dim, mean in agg["mean_scores"].items():
        if mean is not None:
            lines.append(f"- Mean {dim}: {mean:.2f}/5")
        else:
            lines.append(f"- Mean {dim}: n/a (no judge scores)")
    lines.append("")
    if agg["failing_ids"]:
        lines.append("### Failures")
        for r in results:
            if r.get("passed"):
                continue
            cause_parts = []
            for name, check in r.get("deterministic_checks", {}).items():
                if not check["passed"]:
                    cause_parts.append(f"{name}: {check['detail'] or 'failed'}")
            for key in ("profile_check", "eligibility_check", "tool_check"):
                check = r.get(key)
                if check and not check["passed"]:
                    cause_parts.append(f"{key}: {check['detail']}")
            if r.get("judge_overall_pass") is False and r.get("judge_scores"):
                low = [
                    f"{d}={r['judge_scores'][d]} ({r['judge_justifications'].get(d, '')})"
                    for d in DIMENSIONS
                    if r["judge_scores"][d] <= 2
                ]
                if low:
                    cause_parts.append("judge: " + " | ".join(low))
            if r.get("error"):
                cause_parts.append(r["error"])
            cause = "; ".join(cause_parts) if cause_parts else "(no specific cause recorded)"
            lines.append(f"- **{r['id']}** ({r['category']}): {cause}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", choices=["smoke"], default=None)
    parser.add_argument("--cost-cap", type=int, default=None,
                        help="Max judge calls (skip judge after cap). Use to bound CI cost.")
    parser.add_argument("--out-json", type=str, default=None,
                        help="Optional path to write per-case JSON details.")
    args = parser.parse_args()

    reset_judge_calls()
    cases = _load_cases(args.subset)
    log.info("Loaded %d cases (subset=%s)", len(cases), args.subset)

    results: list[dict] = []
    for case in cases:
        try:
            results.append(run_one_case(case, cost_cap=args.cost_cap))
        except JudgeAccessError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(2)
        except Exception as e:
            log.error("Unhandled error in case %s: %s\n%s", case["id"], e, traceback.format_exc())
            results.append({
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "error": f"runner_exception: {e}",
            })

    agg = aggregate(results)
    section = render_section(results, agg)
    print(section)

    total_judge = sum(r.get("judge_calls", 0) for r in results)
    total_agent_calls = sum(r.get("agent_calls", 0) for r in results)
    cost_est = estimate_cost_usd(total_agent_calls, total_judge)

    append_history({
        "kind": "conversation_evals",
        "subset": args.subset,
        "agent_model": MODEL_ID,
        "judge_model": JUDGE_MODEL_ID,
        "total_cases": agg["total"],
        "passed": agg["passed"],
        "pass_rate": agg["pass_rate"],
        "mean_scores": agg["mean_scores"],
        "failing_ids": agg["failing_ids"],
        "agent_calls": total_agent_calls,
        "judge_calls": total_judge,
        "estimated_cost_usd": cost_est,
    })

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump({"aggregate": agg, "results": results}, f, indent=2)


if __name__ == "__main__":
    main()
