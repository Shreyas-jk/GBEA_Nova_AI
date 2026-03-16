"""Deterministic eligibility rules engine — no LLM calls.

Each program's eligibility is evaluated with pure Python logic using the
Federal Poverty Level table and program-specific rules.
"""

from __future__ import annotations

from config import fpl_for_household


def _income_below_fpl_pct(profile: dict, pct: int) -> bool | None:
    """Return True if household income is below *pct*% of FPL, None if unknown."""
    income = profile.get("annual_income")
    hh = profile.get("household_size")
    if income is None or hh is None:
        return None
    threshold = fpl_for_household(hh) * pct / 100
    return income <= threshold


def _has_children_under(profile: dict, age: int) -> bool | None:
    """Check whether the profile has children under *age*."""
    ages = profile.get("children_ages")
    if ages and isinstance(ages, list):
        return any(a < age for a in ages)
    if profile.get("has_children"):
        return None  # has kids but ages unknown
    return False


def check_program_eligibility(profile: dict, program: dict) -> dict:
    """Evaluate a single program against a citizen profile.

    Returns:
        dict with keys: eligible (bool), confidence (str), reason (str),
        estimated_benefit (str)
    """
    pid = program["id"]

    # Dispatch to program-specific checker if one exists
    checker = _PROGRAM_CHECKERS.get(pid, _generic_check)
    return checker(profile, program)


# ---------------------------------------------------------------------------
# Generic checker (works for most FPL-based programs)
# ---------------------------------------------------------------------------

def _generic_check(profile: dict, program: dict) -> dict:
    reasons: list[str] = []
    disqualifiers: list[str] = []
    unknowns: list[str] = []

    # --- Citizenship ---
    if program.get("requires_citizenship"):
        cit = profile.get("is_citizen_or_legal_resident")
        if cit is True:
            reasons.append("U.S. citizen or legal resident")
        elif cit is False:
            disqualifiers.append("Program requires U.S. citizenship or legal residency")
        else:
            unknowns.append("citizenship status unknown")

    # --- Income vs FPL ---
    fpl_pct = program.get("income_limit_fpl_pct")
    if fpl_pct:
        result = _income_below_fpl_pct(profile, fpl_pct)
        if result is True:
            reasons.append(f"Income is below {fpl_pct}% FPL")
        elif result is False:
            disqualifiers.append(f"Income exceeds {fpl_pct}% FPL limit")
        else:
            unknowns.append("income or household size unknown")

    # --- Absolute income limit ---
    abs_limit = program.get("income_limit_absolute")
    if abs_limit and profile.get("annual_income") is not None:
        if profile["annual_income"] <= abs_limit:
            reasons.append(f"Income within ${abs_limit:,} limit")
        else:
            disqualifiers.append(f"Income exceeds ${abs_limit:,} limit")

    # --- Children requirement ---
    if program.get("requires_children"):
        if profile.get("has_children"):
            reasons.append("Has dependent children")
        elif profile.get("has_children") is False:
            disqualifiers.append("Program requires dependent children")
        else:
            unknowns.append("children status unknown")

    # --- Pregnancy ---
    if program.get("requires_pregnancy"):
        if profile.get("is_pregnant"):
            reasons.append("Currently pregnant")
        elif profile.get("is_pregnant") is False:
            disqualifiers.append("Program requires pregnancy")
        else:
            unknowns.append("pregnancy status unknown")

    # --- Disability ---
    if program.get("requires_disability"):
        if profile.get("is_disabled"):
            reasons.append("Has qualifying disability")
        elif profile.get("is_disabled") is False:
            disqualifiers.append("Program requires disability")
        else:
            unknowns.append("disability status unknown")

    # --- Veteran ---
    if program.get("requires_veteran"):
        if profile.get("is_veteran"):
            reasons.append("Is a veteran")
        elif profile.get("is_veteran") is False:
            disqualifiers.append("Program requires veteran status")
        else:
            unknowns.append("veteran status unknown")

    return _build_result(program, reasons, disqualifiers, unknowns)


def _build_result(
    program: dict,
    reasons: list[str],
    disqualifiers: list[str],
    unknowns: list[str],
) -> dict:
    if disqualifiers:
        return {
            "eligible": False,
            "confidence": "high" if not unknowns else "medium",
            "reason": "; ".join(disqualifiers),
            "estimated_benefit": program.get("estimated_benefit", "N/A"),
        }
    if unknowns and not reasons:
        return {
            "eligible": True,
            "confidence": "low",
            "reason": "Possibly eligible — " + "; ".join(unknowns),
            "estimated_benefit": program.get("estimated_benefit", "N/A"),
        }
    if unknowns:
        return {
            "eligible": True,
            "confidence": "medium",
            "reason": "; ".join(reasons) + " (but " + "; ".join(unknowns) + ")",
            "estimated_benefit": program.get("estimated_benefit", "N/A"),
        }
    return {
        "eligible": True,
        "confidence": "high",
        "reason": "; ".join(reasons) if reasons else "Meets basic criteria",
        "estimated_benefit": program.get("estimated_benefit", "N/A"),
    }


# ---------------------------------------------------------------------------
# Program-specific checkers
# ---------------------------------------------------------------------------

def _check_snap(profile: dict, program: dict) -> dict:
    return _generic_check(profile, program)


def _check_medicaid(profile: dict, program: dict) -> dict:
    return _generic_check(profile, program)


def _check_chip(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    # Income
    result = _income_below_fpl_pct(profile, 200)
    if result is True:
        reasons.append("Income below 200% FPL")
    elif result is False:
        disq.append("Income exceeds 200% FPL")
    else:
        unk.append("income unknown")

    # Children under 19
    has_kids = profile.get("has_children")
    ages = profile.get("children_ages")
    if has_kids is False:
        disq.append("Must have children under 19")
    elif ages:
        if any(a < 19 for a in ages):
            reasons.append("Has children under 19")
        else:
            disq.append("All children are 19 or older")
    elif has_kids:
        reasons.append("Has children (ages not confirmed)")
        unk.append("children's ages unknown")
    else:
        unk.append("children status unknown")

    return _build_result(program, reasons, disq, unk)


def _check_wic(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Income
    result = _income_below_fpl_pct(profile, 185)
    if result is True:
        reasons.append("Income below 185% FPL")
    elif result is False:
        disq.append("Income exceeds 185% FPL")
    else:
        unk.append("income unknown")

    # Must be pregnant, postpartum, or have children under 5
    pregnant = profile.get("is_pregnant")
    kids_under_5 = _has_children_under(profile, 5)

    if pregnant is True:
        reasons.append("Currently pregnant")
    elif kids_under_5 is True:
        reasons.append("Has children under 5")
    elif pregnant is False and kids_under_5 is False:
        disq.append("Must be pregnant, postpartum, or have children under 5")
    else:
        unk.append("pregnancy/young children status unknown")

    return _build_result(program, reasons, disq, unk)


def _check_eitc(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    # Earned income required
    emp = profile.get("employment_status")
    if emp in ("employed", "part-time", "self-employed"):
        reasons.append("Has earned income")
    elif emp in ("unemployed", "retired"):
        disq.append("Must have earned income (wages or self-employment)")
    elif emp == "student":
        unk.append("student employment status unclear")
    else:
        unk.append("employment status unknown")

    # Income limits based on number of children
    income = profile.get("annual_income")
    ages = profile.get("children_ages")
    has_kids = profile.get("has_children")

    if income is not None:
        limits = program.get("income_limits", {})
        if ages:
            num_kids = len(ages)
        elif has_kids:
            num_kids = 1  # assume at least 1
        else:
            num_kids = 0

        if num_kids == 0:
            limit = limits.get("0_children", 18591)
        elif num_kids == 1:
            limit = limits.get("1_child", 49084)
        elif num_kids == 2:
            limit = limits.get("2_children", 55768)
        else:
            limit = limits.get("3_plus_children", 59899)

        if income <= limit:
            reasons.append(f"Income within EITC limit (${limit:,} for {num_kids} children)")
        else:
            disq.append(f"Income exceeds EITC limit of ${limit:,}")
    else:
        unk.append("income unknown")

    return _build_result(program, reasons, disq, unk)


def _check_child_tax_credit(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Children under 17
    has_kids = profile.get("has_children")
    ages = profile.get("children_ages")

    if has_kids is False:
        disq.append("Must have qualifying children under 17")
    elif ages:
        under_17 = [a for a in ages if a < 17]
        if under_17:
            reasons.append(f"Has {len(under_17)} child(ren) under 17")
        else:
            disq.append("No children under 17")
    elif has_kids:
        reasons.append("Has children (ages not confirmed)")
        unk.append("children's ages unknown")
    else:
        unk.append("children status unknown")

    # Income phase-out (use single limit as conservative default)
    income = profile.get("annual_income")
    if income is not None:
        limit = 200_000  # single filer limit
        if income <= limit:
            reasons.append(f"Income within phase-out threshold")
        else:
            disq.append("Income may exceed Child Tax Credit phase-out")
    else:
        unk.append("income unknown")

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    return _build_result(program, reasons, disq, unk)


def _check_pell_grant(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    # Must be a student / enrolled
    emp = profile.get("employment_status")
    if emp == "student":
        reasons.append("Currently a student")
    else:
        unk.append("enrollment in undergraduate program unknown")

    # Income
    income = profile.get("annual_income")
    if income is not None:
        if income <= 60_000:
            reasons.append("Income within typical Pell Grant range")
        else:
            disq.append("Income likely too high for Pell Grant (typically under $60,000)")
    else:
        unk.append("income unknown")

    return _build_result(program, reasons, disq, unk)


def _check_tanf(profile: dict, program: dict) -> dict:
    return _generic_check(profile, program)


def _check_section8(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    # Income — use rough 50% AMI approximation (~$40k for a family of 4 nationally)
    income = profile.get("annual_income")
    hh = profile.get("household_size")
    if income is not None and hh is not None:
        # Rough national AMI estimate: $80k for household of 4, scaled
        ami_est = 80_000 + (hh - 4) * 5_000
        if income <= ami_est * 0.50:
            reasons.append("Income likely below 50% of Area Median Income")
        else:
            disq.append("Income may exceed 50% AMI limit for Section 8")
    else:
        unk.append("income or household size unknown")

    reasons.append("Note: Section 8 has very long waitlists (often 1-3+ years)")

    return _build_result(program, reasons, disq, unk)


def _check_ssi(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Citizenship
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    # Must be 65+ OR disabled OR blind
    elderly = profile.get("is_elderly")
    disabled = profile.get("is_disabled")
    if elderly or disabled:
        if elderly:
            reasons.append("Aged 65 or older")
        if disabled:
            reasons.append("Has qualifying disability")
    elif elderly is False and disabled is False:
        disq.append("Must be aged 65+, blind, or disabled")
    else:
        unk.append("age/disability status unknown")

    # Income
    income = profile.get("annual_income")
    if income is not None:
        if income <= 11_316:
            reasons.append("Income within SSI limits")
        else:
            disq.append("Income likely exceeds SSI limits (~$943/month)")
    else:
        unk.append("income unknown")

    return _build_result(program, reasons, disq, unk)


def _check_lifeline(profile: dict, program: dict) -> dict:
    return _generic_check(profile, program)


# State program checkers

def _check_calfresh(profile: dict, program: dict) -> dict:
    """CalFresh uses 200% FPL gross income in CA (broad-based categorical eligibility)."""
    reasons, disq, unk = [], [], []

    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    result = _income_below_fpl_pct(profile, 200)
    if result is True:
        reasons.append("Income below 200% FPL (CalFresh uses broad-based categorical eligibility)")
    elif result is False:
        disq.append("Income exceeds CalFresh 200% FPL limit")
    else:
        unk.append("income unknown")

    state = profile.get("state")
    if state and state.upper() != "CA":
        disq.append("CalFresh is only for California residents")

    return _build_result(program, reasons, disq, unk)


def _check_medi_cal(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    result = _income_below_fpl_pct(profile, 138)
    if result is True:
        reasons.append("Income below 138% FPL")
    elif result is False:
        disq.append("Income exceeds Medi-Cal 138% FPL limit")
    else:
        unk.append("income unknown")

    state = profile.get("state")
    if state and state.upper() != "CA":
        disq.append("Medi-Cal is only for California residents")

    # Medi-Cal expanded to all regardless of immigration status
    reasons.append("Medi-Cal is available regardless of immigration status in California")

    return _build_result(program, reasons, disq, unk)


def _check_calworks(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    cit = profile.get("is_citizen_or_legal_resident")
    if cit is True:
        reasons.append("U.S. citizen or legal resident")
    elif cit is False:
        disq.append("Requires citizenship or legal residency")
    else:
        unk.append("citizenship unknown")

    result = _income_below_fpl_pct(profile, 100)
    if result is True:
        reasons.append("Income below 100% FPL")
    elif result is False:
        disq.append("Income exceeds CalWORKs limit")
    else:
        unk.append("income unknown")

    if profile.get("has_children"):
        reasons.append("Has dependent children")
    elif profile.get("has_children") is False:
        disq.append("Must have dependent children")
    else:
        unk.append("children status unknown")

    state = profile.get("state")
    if state and state.upper() != "CA":
        disq.append("CalWORKs is only for California residents")

    return _build_result(program, reasons, disq, unk)


def _check_care(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    result = _income_below_fpl_pct(profile, 200)
    if result is True:
        reasons.append("Income below 200% FPL")
    elif result is False:
        disq.append("Income exceeds CARE 200% FPL limit")
    else:
        unk.append("income unknown")

    state = profile.get("state")
    if state and state.upper() != "CA":
        disq.append("CARE is only for California residents")

    return _build_result(program, reasons, disq, unk)


def _check_capi(profile: dict, program: dict) -> dict:
    reasons, disq, unk = [], [], []

    # Must NOT be a citizen (CAPI is for non-citizens ineligible for SSI)
    cit = profile.get("is_citizen_or_legal_resident")
    if cit is False:
        reasons.append("Non-citizen (CAPI is for immigrants ineligible for SSI)")
    elif cit is True:
        disq.append("CAPI is for non-citizens who are ineligible for SSI")
    else:
        unk.append("citizenship status unknown")

    # Must be 65+, blind, or disabled
    elderly = profile.get("is_elderly")
    disabled = profile.get("is_disabled")
    if elderly or disabled:
        reasons.append("Meets age/disability requirement")
    elif elderly is False and disabled is False:
        disq.append("Must be aged 65+, blind, or disabled")
    else:
        unk.append("age/disability status unknown")

    income = profile.get("annual_income")
    if income is not None:
        if income <= 11_316:
            reasons.append("Income within CAPI limits")
        else:
            disq.append("Income likely exceeds CAPI limits")
    else:
        unk.append("income unknown")

    state = profile.get("state")
    if state and state.upper() != "CA":
        disq.append("CAPI is only for California residents")

    return _build_result(program, reasons, disq, unk)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROGRAM_CHECKERS = {
    "snap": _check_snap,
    "medicaid": _check_medicaid,
    "chip": _check_chip,
    "wic": _check_wic,
    "liheap": _generic_check,
    "section8": _check_section8,
    "eitc": _check_eitc,
    "child_tax_credit": _check_child_tax_credit,
    "pell_grant": _check_pell_grant,
    "tanf": _check_tanf,
    "ssi": _check_ssi,
    "lifeline": _check_lifeline,
    # California state programs
    "calfresh": _check_calfresh,
    "medi_cal": _check_medi_cal,
    "calworks": _check_calworks,
    "care": _check_care,
    "capi": _check_capi,
}
