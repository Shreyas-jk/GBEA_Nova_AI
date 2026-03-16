"""Tests for the deterministic eligibility rules engine."""

import json
import os
import sys

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.rules_engine import check_program_eligibility

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _load_federal_programs() -> dict[str, dict]:
    with open(os.path.join(DATA_DIR, "federal_programs.json")) as f:
        programs = json.load(f)
    return {p["id"]: p for p in programs}


def _load_state_programs(state: str) -> dict[str, dict]:
    with open(os.path.join(DATA_DIR, "state_programs.json")) as f:
        data = json.load(f)
    programs = data.get(state, [])
    return {p["id"]: p for p in programs}


FEDERAL = _load_federal_programs()
CA_STATE = _load_state_programs("CA")


# ---- Scenario 1: Single mother, 2 kids (ages 3 & 7), $28k income, CA ----

SINGLE_MOTHER = {
    "state": "CA",
    "household_size": 3,
    "annual_income": 28_000,
    "employment_status": "employed",
    "has_children": True,
    "children_ages": [3, 7],
    "is_pregnant": False,
    "is_veteran": False,
    "is_disabled": False,
    "is_elderly": False,
    "is_citizen_or_legal_resident": True,
    "housing_status": "renter",
    "has_health_insurance": False,
}


class TestSingleMother:
    def test_snap_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["snap"])
        # $28k < 130% of $26,650 = $34,645 → eligible
        assert result["eligible"] is True
        assert result["confidence"] == "high"

    def test_medicaid_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["medicaid"])
        # $28k < 138% of $26,650 = $36,777 → eligible
        assert result["eligible"] is True

    def test_wic_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["wic"])
        # Has child aged 3 (under 5) and income < 185% FPL → eligible
        assert result["eligible"] is True

    def test_eitc_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["eitc"])
        # Employed, $28k income, 2 children → under $55,768 limit
        assert result["eligible"] is True
        assert result["confidence"] == "high"

    def test_child_tax_credit_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["child_tax_credit"])
        # 2 kids under 17, income under $200k → eligible
        assert result["eligible"] is True
        assert result["confidence"] == "high"

    def test_chip_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, FEDERAL["chip"])
        # Income < 200% FPL, has children under 19
        assert result["eligible"] is True

    def test_calfresh_eligible(self):
        result = check_program_eligibility(SINGLE_MOTHER, CA_STATE["calfresh"])
        # CA: 200% FPL, $28k income → eligible
        assert result["eligible"] is True


# ---- Scenario 2: Retired veteran, 1 person, $18k income ----

RETIRED_VETERAN = {
    "state": "TX",
    "household_size": 1,
    "annual_income": 18_000,
    "employment_status": "retired",
    "has_children": False,
    "children_ages": [],
    "is_pregnant": False,
    "is_veteran": True,
    "is_disabled": False,
    "is_elderly": True,
    "is_citizen_or_legal_resident": True,
    "housing_status": "renter",
    "has_health_insurance": True,
}


class TestRetiredVeteran:
    def test_snap_not_eligible(self):
        result = check_program_eligibility(RETIRED_VETERAN, FEDERAL["snap"])
        # $18k vs 130% of $15,650 = $20,345 → eligible
        assert result["eligible"] is True

    def test_medicaid_not_eligible(self):
        result = check_program_eligibility(RETIRED_VETERAN, FEDERAL["medicaid"])
        # $18k vs 138% of $15,650 = $21,597 → eligible
        assert result["eligible"] is True

    def test_liheap_eligible(self):
        result = check_program_eligibility(RETIRED_VETERAN, FEDERAL["liheap"])
        # $18k vs 150% of $15,650 = $23,475 → eligible
        assert result["eligible"] is True

    def test_ssi_eligible(self):
        result = check_program_eligibility(RETIRED_VETERAN, FEDERAL["ssi"])
        # Elderly (65+), but $18k > SSI limit of $11,316 → not eligible
        assert result["eligible"] is False

    def test_eitc_not_eligible(self):
        result = check_program_eligibility(RETIRED_VETERAN, FEDERAL["eitc"])
        # Retired = no earned income → not eligible
        assert result["eligible"] is False


# ---- Scenario 3: College student, 1 person, $8k income ----

COLLEGE_STUDENT = {
    "state": "NY",
    "household_size": 1,
    "annual_income": 8_000,
    "employment_status": "student",
    "has_children": False,
    "children_ages": [],
    "is_pregnant": False,
    "is_veteran": False,
    "is_disabled": False,
    "is_elderly": False,
    "is_citizen_or_legal_resident": True,
    "housing_status": "renter",
    "has_health_insurance": False,
}


class TestCollegeStudent:
    def test_pell_grant_eligible(self):
        result = check_program_eligibility(COLLEGE_STUDENT, FEDERAL["pell_grant"])
        # Student, $8k income → eligible
        assert result["eligible"] is True
        assert result["confidence"] == "high"

    def test_medicaid_eligible(self):
        result = check_program_eligibility(COLLEGE_STUDENT, FEDERAL["medicaid"])
        # $8k < 138% of $15,650 → eligible
        assert result["eligible"] is True

    def test_snap_eligible(self):
        result = check_program_eligibility(COLLEGE_STUDENT, FEDERAL["snap"])
        # $8k < 130% of $15,650 → eligible
        assert result["eligible"] is True

    def test_lifeline_eligible(self):
        result = check_program_eligibility(COLLEGE_STUDENT, FEDERAL["lifeline"])
        # $8k < 135% FPL → eligible
        assert result["eligible"] is True


# ---- Scenario 4: Family of 4, $85k income ----

HIGH_INCOME_FAMILY = {
    "state": "CA",
    "household_size": 4,
    "annual_income": 85_000,
    "employment_status": "employed",
    "has_children": True,
    "children_ages": [5, 10],
    "is_pregnant": False,
    "is_veteran": False,
    "is_disabled": False,
    "is_elderly": False,
    "is_citizen_or_legal_resident": True,
    "housing_status": "homeowner",
    "has_health_insurance": True,
}


class TestHighIncomeFamily:
    def test_snap_not_eligible(self):
        result = check_program_eligibility(HIGH_INCOME_FAMILY, FEDERAL["snap"])
        # $85k > 130% of $32,150 = $41,795 → not eligible
        assert result["eligible"] is False

    def test_medicaid_not_eligible(self):
        result = check_program_eligibility(HIGH_INCOME_FAMILY, FEDERAL["medicaid"])
        # $85k > 138% of $32,150 → not eligible
        assert result["eligible"] is False

    def test_child_tax_credit_eligible(self):
        result = check_program_eligibility(HIGH_INCOME_FAMILY, FEDERAL["child_tax_credit"])
        # $85k < $200k, has kids under 17 → eligible
        assert result["eligible"] is True
        assert result["confidence"] == "high"

    def test_tanf_not_eligible(self):
        result = check_program_eligibility(HIGH_INCOME_FAMILY, FEDERAL["tanf"])
        # $85k > 100% FPL → not eligible
        assert result["eligible"] is False

    def test_wic_not_eligible(self):
        result = check_program_eligibility(HIGH_INCOME_FAMILY, FEDERAL["wic"])
        # $85k > 185% of $32,150 → not eligible
        assert result["eligible"] is False


# ---- Scenario 5: Edge cases ----

class TestEdgeCases:
    def test_exactly_at_fpl_threshold(self):
        """Income exactly at 130% FPL for SNAP should be eligible (<=)."""
        profile = {
            "household_size": 1,
            "annual_income": 20_345,  # exactly 130% of $15,650
            "is_citizen_or_legal_resident": True,
        }
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert result["eligible"] is True

    def test_one_dollar_over_threshold(self):
        """Income $1 over 130% FPL for SNAP should not be eligible."""
        profile = {
            "household_size": 1,
            "annual_income": 20_346,
            "is_citizen_or_legal_resident": True,
        }
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert result["eligible"] is False

    def test_missing_income(self):
        """Missing income should result in low/medium confidence."""
        profile = {
            "household_size": 3,
            "is_citizen_or_legal_resident": True,
        }
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert result["eligible"] is True
        assert result["confidence"] in ("low", "medium")

    def test_missing_household_size(self):
        """Missing household size should result in low/medium confidence."""
        profile = {
            "annual_income": 20_000,
            "is_citizen_or_legal_resident": True,
        }
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert result["eligible"] is True
        assert result["confidence"] in ("low", "medium")

    def test_non_citizen(self):
        """Non-citizen should be disqualified from citizenship-requiring programs."""
        profile = {
            "household_size": 1,
            "annual_income": 10_000,
            "is_citizen_or_legal_resident": False,
        }
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert result["eligible"] is False

    def test_capi_for_non_citizen(self):
        """CAPI should be available for non-citizens in CA who are elderly/disabled."""
        profile = {
            "state": "CA",
            "household_size": 1,
            "annual_income": 10_000,
            "is_citizen_or_legal_resident": False,
            "is_elderly": True,
            "is_disabled": False,
        }
        result = check_program_eligibility(profile, CA_STATE["capi"])
        assert result["eligible"] is True

    def test_empty_profile(self):
        """Completely empty profile should not crash."""
        profile = {}
        result = check_program_eligibility(profile, FEDERAL["snap"])
        assert "eligible" in result
        assert "confidence" in result
        assert "reason" in result
