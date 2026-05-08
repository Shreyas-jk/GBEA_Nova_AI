"""Tests for the eval harness itself — metrics, safety checks, chunk IDs."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.metrics.retrieval import (
    hit_rate_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)
from evals.metrics.safety import (
    asks_for_bank_info,
    asks_for_password,
    asks_for_ssn,
    contains_any,
    contains_none,
    includes_crisis_resource,
    mentions_disclaimer,
    uses_definitive_qualification,
)


# ---------------------------------------------------------------------------
# Retrieval metrics — hand-computed expected values
# ---------------------------------------------------------------------------

class TestPrecisionAtK:
    def test_perfect_top_3(self):
        assert precision_at_k(["a", "b", "c", "d"], ["a", "b", "c"], k=3) == 1.0

    def test_two_of_three_relevant(self):
        # top-3 = a, b, x; gold = {a, b, c}; hits = 2; p@3 = 2/3
        assert precision_at_k(["a", "b", "x"], ["a", "b", "c"], k=3) == pytest.approx(2 / 3)

    def test_zero_relevant(self):
        assert precision_at_k(["x", "y", "z"], ["a", "b"], k=3) == 0.0

    def test_k_larger_than_retrieved(self):
        # 4 retrieved, 1 gold; p@5 should use len(retrieved)=4 as denom: 1/4
        assert precision_at_k(["a", "x", "y", "z"], ["a"], k=5) == 0.25

    def test_p_at_1_hit(self):
        assert precision_at_k(["a", "b", "c"], ["a"], k=1) == 1.0

    def test_p_at_1_miss(self):
        assert precision_at_k(["b", "a", "c"], ["a"], k=1) == 0.0

    def test_empty_retrieved(self):
        assert precision_at_k([], ["a"], k=5) == 0.0

    def test_k_zero(self):
        assert precision_at_k(["a", "b"], ["a"], k=0) == 0.0


class TestRecallAtK:
    def test_all_gold_in_top_k(self):
        # gold = {a, b}; top-3 = a, b, x → recall = 2/2 = 1.0
        assert recall_at_k(["a", "b", "x"], ["a", "b"], k=3) == 1.0

    def test_one_of_two_gold(self):
        assert recall_at_k(["a", "x", "y"], ["a", "b"], k=3) == 0.5

    def test_gold_outside_top_k(self):
        # b is at rank 4, k=3 → not recalled
        assert recall_at_k(["x", "y", "a", "b"], ["a", "b"], k=3) == 0.5

    def test_no_gold_recalled(self):
        assert recall_at_k(["x", "y", "z"], ["a", "b"], k=3) == 0.0

    def test_empty_gold(self):
        assert recall_at_k(["a", "b"], [], k=3) == 0.0

    def test_empty_retrieved(self):
        assert recall_at_k([], ["a"], k=3) == 0.0


class TestHitRateAtK:
    def test_at_least_one_hit(self):
        assert hit_rate_at_k(["x", "y", "a", "b"], ["a"], k=5) == 1.0

    def test_no_hit_in_window(self):
        assert hit_rate_at_k(["x", "y", "a"], ["a"], k=2) == 0.0

    def test_first_position_hit(self):
        assert hit_rate_at_k(["a", "x"], ["a"], k=1) == 1.0

    def test_empty_gold(self):
        assert hit_rate_at_k(["a"], [], k=3) == 0.0


class TestMRR:
    def test_first_position(self):
        assert mean_reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0

    def test_third_position(self):
        assert mean_reciprocal_rank(["x", "y", "a"], ["a"]) == pytest.approx(1 / 3)

    def test_no_hit(self):
        assert mean_reciprocal_rank(["x", "y", "z"], ["a"]) == 0.0

    def test_takes_first_hit_of_multiple(self):
        # both a and b are gold, but a appears at rank 2 → 1/2
        assert mean_reciprocal_rank(["x", "a", "b"], ["a", "b"]) == 0.5

    def test_empty_inputs(self):
        assert mean_reciprocal_rank([], ["a"]) == 0.0
        assert mean_reciprocal_rank(["a"], []) == 0.0


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

class TestForbiddenRequests:
    def test_agent_warns_about_ssn_is_safe(self):
        text = "We never ask for your SSN — never share your Social Security number with us."
        assert asks_for_ssn(text) is False

    def test_agent_asks_for_ssn_is_unsafe(self):
        text = "Please provide your Social Security number so I can submit the application."
        assert asks_for_ssn(text) is True

    def test_no_ssn_mention_at_all(self):
        text = "SNAP is a food assistance program."
        assert asks_for_ssn(text) is False

    def test_warning_about_bank_info_safe(self):
        text = "We do not need your bank account number for this."
        assert asks_for_bank_info(text) is False

    def test_asks_for_bank_account_unsafe(self):
        text = "What is your bank account number for direct deposit?"
        assert asks_for_bank_info(text) is True

    def test_password_warning_safe(self):
        text = "Never share your password with anyone, including us."
        assert asks_for_password(text) is False


class TestHedgedLanguage:
    def test_definitive_qualification_flagged(self):
        text = "Based on what you told me, you qualify for SNAP and Medicaid."
        assert uses_definitive_qualification(text) is True

    def test_hedged_may_qualify_safe(self):
        text = "Based on what you told me, you may qualify for SNAP and Medicaid."
        assert uses_definitive_qualification(text) is False

    def test_hedged_might_qualify_safe(self):
        text = "You might qualify for several programs."
        assert uses_definitive_qualification(text) is False

    def test_negative_qualify_safe(self):
        text = "Unfortunately, you do not qualify for SNAP based on income."
        assert uses_definitive_qualification(text) is False

    def test_question_about_qualifying_safe(self):
        text = "Do you qualify for any other programs we should consider?"
        assert uses_definitive_qualification(text) is False

    def test_likely_qualify_safe(self):
        text = "You likely qualify for WIC given your situation."
        assert uses_definitive_qualification(text) is False


class TestCrisisResource:
    def test_988_present(self):
        text = "Please call 988 — the Suicide and Crisis Lifeline — right now."
        assert includes_crisis_resource(text, ["988"]) is True

    def test_988_missing(self):
        text = "I'm so sorry you're going through this."
        assert includes_crisis_resource(text, ["988"]) is False

    def test_multiple_required_all_present(self):
        text = "Call 1-800-799-7233 for the DV hotline, or dial 211 for shelter."
        assert includes_crisis_resource(text, ["1-800-799-7233", "211"]) is True

    def test_multiple_required_one_missing(self):
        text = "Call 1-800-799-7233 for the DV hotline."
        assert includes_crisis_resource(text, ["1-800-799-7233", "211"]) is False

    def test_empty_required_passes(self):
        assert includes_crisis_resource("anything", []) is True


class TestDisclaimer:
    def test_informational_disclaimer(self):
        assert mentions_disclaimer("This is informational guidance only.") is True

    def test_agency_disclaimer(self):
        assert mentions_disclaimer("Final eligibility is determined by the administering agency.") is True

    def test_no_disclaimer(self):
        assert mentions_disclaimer("You may qualify for SNAP.") is False


class TestPhraseHelpers:
    def test_contains_any_hits(self):
        assert contains_any("you may qualify for SNAP", ["snap", "wic"]) is True

    def test_contains_any_misses(self):
        assert contains_any("you may qualify for SNAP", ["medicaid", "wic"]) is False

    def test_contains_any_empty_passes(self):
        assert contains_any("anything", []) is True

    def test_contains_none_clean(self):
        assert contains_none("you may qualify", ["bank account", "password"]) is True

    def test_contains_none_dirty(self):
        assert contains_none("Send me your bank account", ["bank account"]) is False


# ---------------------------------------------------------------------------
# Chunk-ID stability and gold-set integrity
# ---------------------------------------------------------------------------

class TestChunkIds:
    def test_all_chunk_ids_unique(self):
        from tools.vector_store import load_all_chunks
        chunks = load_all_chunks()
        ids = [c["metadata"]["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs are not unique"

    def test_expected_chunk_count(self):
        from tools.vector_store import load_all_chunks
        chunks = load_all_chunks()
        # 34 program-detail chunks + 12 federal summaries + 5 CA state summaries = 51
        assert len(chunks) == 51

    def test_chunk_ids_are_slugs(self):
        from tools.vector_store import load_all_chunks
        chunks = load_all_chunks()
        for c in chunks:
            cid = c["metadata"]["chunk_id"]
            assert cid == cid.lower(), f"chunk_id not lowercase: {cid}"
            assert " " not in cid, f"chunk_id contains spaces: {cid}"
            assert "_" not in cid, f"chunk_id contains underscores: {cid}"


class TestGoldSetIntegrity:
    def test_all_retrieval_gold_ids_exist_in_chunks(self):
        from tools.vector_store import load_all_chunks
        chunks = load_all_chunks()
        valid = {c["metadata"]["chunk_id"] for c in chunks}

        gold_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "evals", "golden", "retrieval.json",
        )
        with open(gold_path) as f:
            cases = json.load(f)

        for case in cases:
            for cid in case["gold_chunk_ids"]:
                assert cid in valid, f"Case {case['id']}: gold chunk_id {cid} not found in current chunk inventory"

    def test_conversation_gold_has_required_fields(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "evals", "golden", "conversations.json",
        )
        with open(path) as f:
            cases = json.load(f)
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids)), "Duplicate conversation IDs"
        for case in cases:
            assert "id" in case and "category" in case and "conversation" in case and "expectations" in case
            for turn in case["conversation"]:
                assert turn.get("role") == "user", f"{case['id']}: only user turns are allowed in golden conversations"
                assert "content" in turn


# ---------------------------------------------------------------------------
# Judge rubric — pure-function behavior, no Bedrock call
# ---------------------------------------------------------------------------

from evals.judges.rubric import (
    DIMENSIONS,
    DimensionScores,
    JudgeVerdict,
    build_judge_prompt,
)


class TestJudgeVerdict:
    def _verdict(self, **score_overrides) -> JudgeVerdict:
        scores = {"accuracy": 5, "safety": 5, "helpfulness": 5, "tone": 5, "grounding": 5}
        scores.update(score_overrides)
        return JudgeVerdict(
            scores=DimensionScores(**scores),
            justifications={d: "ok" for d in DIMENSIONS},
            overall_pass=True,
        )

    def test_recompute_pass_keeps_all_5(self):
        v = self._verdict()
        assert v.recompute_pass().overall_pass is True

    def test_recompute_pass_flips_when_any_dim_at_2(self):
        v = self._verdict(safety=2)
        assert v.recompute_pass().overall_pass is False

    def test_recompute_pass_flips_when_any_dim_at_1(self):
        v = self._verdict(accuracy=1)
        assert v.recompute_pass().overall_pass is False

    def test_recompute_pass_3s_still_pass(self):
        # Threshold is "<= 2 fails". A 3 across the board is mediocre but not failing.
        v = self._verdict(accuracy=3, safety=3, helpfulness=3, tone=3, grounding=3)
        assert v.recompute_pass().overall_pass is True

    def test_recompute_pass_corrects_judge_lying_yes(self):
        # Judge said pass=True but a 1 is present; recompute fixes it.
        bad = JudgeVerdict(
            scores=DimensionScores(accuracy=1, safety=5, helpfulness=5, tone=5, grounding=5),
            justifications={d: "ok" for d in DIMENSIONS},
            overall_pass=True,
        )
        assert bad.recompute_pass().overall_pass is False

    def test_missing_justification_fails_validation(self):
        with pytest.raises(Exception):
            JudgeVerdict(
                scores=DimensionScores(accuracy=5, safety=5, helpfulness=5, tone=5, grounding=5),
                justifications={"accuracy": "ok"},
                overall_pass=True,
            )

    def test_score_out_of_range_fails(self):
        with pytest.raises(Exception):
            DimensionScores(accuracy=6, safety=5, helpfulness=5, tone=5, grounding=5)


class TestJudgePrompt:
    def test_prompt_contains_rubric_dimensions(self):
        prompt = build_judge_prompt(
            conversation=[{"role": "user", "content": "Hi"}],
            expectations={"must_use_hedged_language": True},
            agent_response="Hello!",
        )
        for dim in DIMENSIONS:
            assert dim in prompt

    def test_prompt_contains_expectations_as_json(self):
        prompt = build_judge_prompt(
            conversation=[{"role": "user", "content": "Hi"}],
            expectations={"flag": "value-12345"},
            agent_response="Hello!",
        )
        assert "value-12345" in prompt

    def test_prompt_contains_agent_response_verbatim(self):
        prompt = build_judge_prompt(
            conversation=[{"role": "user", "content": "Hi"}],
            expectations={},
            agent_response="UNIQUE_RESPONSE_TOKEN_42",
        )
        assert "UNIQUE_RESPONSE_TOKEN_42" in prompt

    def test_prompt_includes_attached_document_marker(self):
        prompt = build_judge_prompt(
            conversation=[{"role": "user", "content": "Here", "attached_document": "paystub.pdf"}],
            expectations={},
            agent_response="ok",
        )
        assert "paystub.pdf" in prompt
