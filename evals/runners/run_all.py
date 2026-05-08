"""Run conversation evals + retrieval evals back-to-back, write a single report.

Output:
  - evals/reports/latest.md (overwritten with full combined report)
  - evals/reports/history.jsonl (one row per sub-runner)

CLI:
  python -m evals.runners.run_all                  # full suite
  python -m evals.runners.run_all --subset smoke   # smoke conversations + full retrieval
  python -m evals.runners.run_all --cost-cap 100   # nightly cap
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import JUDGE_MODEL_ID, MODEL_ID
from evals.judges.llm_judge import (
    JudgeAccessError,
    get_call_count as judge_call_count,
    reset_call_count as reset_judge_calls,
)
from evals.runners import run_conversation_evals as conv
from evals.runners import run_retrieval_evals as retr
from evals.runners._common import estimate_cost_usd, write_latest_report

log = logging.getLogger("eval-all")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _header(subset: str | None, agent_calls: int, judge_calls: int) -> str:
    ts = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cost = estimate_cost_usd(agent_calls, judge_calls)
    subset_label = f" — subset: {subset}" if subset else ""
    return (
        f"# Eval run — {ts}{subset_label}\n\n"
        f"- Agent under test: `{MODEL_ID}`\n"
        f"- Judge model: `{JUDGE_MODEL_ID}`\n"
        f"- Agent invocations: {agent_calls}\n"
        f"- Judge invocations: {judge_calls}\n"
        f"- Estimated cost: ~${cost:.3f} (rough — see _common.py for assumptions)\n\n"
        "---\n\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", choices=["smoke"], default=None,
                        help="Run only smoke-tagged conversation cases (retrieval still runs in full).")
    parser.add_argument("--cost-cap", type=int, default=None,
                        help="Max judge calls before skipping further judging.")
    args = parser.parse_args()

    reset_judge_calls()

    # --- Conversation evals ---
    conv_cases = conv._load_cases(args.subset)
    log.info("Conversation cases: %d", len(conv_cases))
    conv_results = []
    for case in conv_cases:
        try:
            conv_results.append(conv.run_one_case(case, cost_cap=args.cost_cap))
        except JudgeAccessError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(2)
    conv_agg = conv.aggregate(conv_results)
    conv_section = conv.render_section(conv_results, conv_agg)

    # --- Retrieval evals ---
    import json as _json
    with open(retr.GOLDEN_DIR / "retrieval.json") as f:
        retr_cases = _json.load(f)
    log.info("Retrieval queries: %d", len(retr_cases))
    retr_results = [retr.run_one(c) for c in retr_cases]
    retr_agg = retr.aggregate(retr_results)
    retr_section = retr.render_section(retr_results, retr_agg)

    # --- Combined report ---
    total_agent_calls = sum(r.get("agent_calls", 0) for r in conv_results)
    total_judge_calls = sum(r.get("judge_calls", 0) for r in conv_results)
    body = _header(args.subset, total_agent_calls, total_judge_calls) + conv_section + "\n" + retr_section
    write_latest_report(body)
    print(body)

    # --- History ---
    from evals.runners._common import append_history
    append_history({
        "kind": "conversation_evals",
        "subset": args.subset,
        "agent_model": MODEL_ID,
        "judge_model": JUDGE_MODEL_ID,
        "total_cases": conv_agg["total"],
        "passed": conv_agg["passed"],
        "pass_rate": conv_agg["pass_rate"],
        "mean_scores": conv_agg["mean_scores"],
        "failing_ids": conv_agg["failing_ids"],
        "agent_calls": total_agent_calls,
        "judge_calls": total_judge_calls,
        "estimated_cost_usd": estimate_cost_usd(total_agent_calls, total_judge_calls),
    })
    append_history({
        "kind": "retrieval_evals",
        "agent_model": MODEL_ID,
        "total_queries": retr_agg["total"],
        **{k: retr_agg[k] for k in ("p_at_1", "p_at_3", "p_at_5", "r_at_5", "mrr", "hit_at_5")},
    })


if __name__ == "__main__":
    main()
