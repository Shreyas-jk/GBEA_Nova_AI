"""Cross-program optimization rules — deterministic strategic advice.

Identifies dependencies, strategic ordering, and time-sensitive actions
between benefit programs. No LLM calls — pure Python logic.
"""

from __future__ import annotations

import datetime


def get_cross_program_insights(profile: dict, eligible_programs: list[dict]) -> list[dict]:
    """Analyze eligible programs and return strategic cross-program insights.

    Each insight is a dict with:
        - type: "dependency" | "timing" | "efficiency" | "urgency"
        - title: short heading
        - detail: explanation
        - programs: list of program short_names involved
        - priority: 1 (highest) to 5 (lowest)
    """
    insights: list[dict] = []
    eligible_names = {p.get("short_name", p.get("program_name", "")).lower() for p in eligible_programs}

    # --- Rule 1: Medicaid/Medi-Cal → SNAP/CalFresh streamlining ---
    medicaid_eligible = any(n in eligible_names for n in ("medicaid", "medi-cal"))
    snap_eligible = any(n in eligible_names for n in ("snap", "calfresh"))

    if medicaid_eligible and snap_eligible:
        state = profile.get("state", "").upper()
        snap_name = "CalFresh" if state == "CA" else "SNAP"
        medicaid_name = "Medi-Cal" if state == "CA" else "Medicaid"
        insights.append({
            "type": "dependency",
            "title": f"Apply for {medicaid_name} FIRST",
            "detail": (
                f"Once approved for {medicaid_name}, you may be automatically enrolled in "
                f"{snap_name} through categorical eligibility — this can skip the separate "
                f"income verification and speed up your {snap_name} application significantly. "
                f"Many states allow a joint application for both programs."
            ),
            "programs": [medicaid_name, snap_name],
            "priority": 1,
        })

    # --- Rule 2: EITC via IRS Free File ---
    eitc_eligible = "eitc" in eligible_names
    ctc_eligible = "child tax credit" in eligible_names

    if eitc_eligible:
        tax_programs = ["EITC"]
        if ctc_eligible:
            tax_programs.append("Child Tax Credit")
        insights.append({
            "type": "efficiency",
            "title": "File taxes through IRS Free File — don't pay for tax prep",
            "detail": (
                "You can claim your " + " and ".join(tax_programs) + " for free using "
                "IRS Free File (irs.gov/freefile) if your income is under $84,000. "
                "Many paid tax preparers charge $200-400 and may take a cut of your "
                "refund. VITA (Volunteer Income Tax Assistance) sites also offer free "
                "in-person help — call 211 to find one near you."
            ),
            "programs": tax_programs,
            "priority": 2,
        })

    # --- Rule 3: WIC urgency — children age out at 5 ---
    wic_eligible = "wic" in eligible_names
    if wic_eligible:
        children_ages = profile.get("children_ages", [])
        aging_out_soon = [a for a in children_ages if isinstance(a, (int, float)) and 4 <= a < 5]
        if aging_out_soon:
            insights.append({
                "type": "urgency",
                "title": "Apply for WIC NOW — your child is about to age out",
                "detail": (
                    f"You have a child who is {aging_out_soon[0]} years old. WIC benefits "
                    "end when a child turns 5. Apply immediately to receive benefits for "
                    "the remaining months. WIC appointments are usually available within "
                    "1-2 weeks."
                ),
                "programs": ["WIC"],
                "priority": 1,
            })
        elif children_ages and any(a < 5 for a in children_ages if isinstance(a, (int, float))):
            insights.append({
                "type": "urgency",
                "title": "Apply for WIC early — children age out at 5",
                "detail": (
                    "WIC provides nutrition support for children under 5 and pregnant women. "
                    "Apply as soon as possible to maximize the months of benefits your "
                    "family receives. Appointments are usually quick — often same week."
                ),
                "programs": ["WIC"],
                "priority": 2,
            })

    # --- Rule 4: Section 8 waitlist awareness ---
    section8_eligible = "section 8" in eligible_names
    if section8_eligible:
        insights.append({
            "type": "timing",
            "title": "Section 8 waitlists open rarely — get on the list now",
            "detail": (
                "Housing Choice Voucher (Section 8) waitlists can close for years at a time. "
                "If your local housing authority's waitlist is currently open, apply "
                "immediately even if you don't need housing help right now. The wait is "
                "typically 1-3+ years. Check your local housing authority's website or "
                "call them directly. You can also apply to multiple housing authorities."
            ),
            "programs": ["Section 8"],
            "priority": 2,
        })

    # --- Rule 5: LIHEAP seasonal timing ---
    liheap_eligible = "liheap" in eligible_names
    if liheap_eligible:
        month = datetime.date.today().month
        if month in (9, 10, 11):  # Fall
            insights.append({
                "type": "timing",
                "title": "Apply for LIHEAP now — before winter heating bills spike",
                "detail": (
                    "LIHEAP funds are distributed on a first-come, first-served basis "
                    "and often run out. Apply now before winter heating costs arrive. "
                    "Some states also offer weatherization assistance that can permanently "
                    "reduce your energy bills."
                ),
                "programs": ["LIHEAP"],
                "priority": 1,
            })
        elif month in (4, 5, 6):  # Spring/early summer
            insights.append({
                "type": "timing",
                "title": "Apply for LIHEAP cooling assistance before summer",
                "detail": (
                    "Many states offer LIHEAP cooling assistance for summer months. "
                    "Apply before summer billing spikes. Funds are limited and go quickly."
                ),
                "programs": ["LIHEAP"],
                "priority": 2,
            })
        else:
            insights.append({
                "type": "timing",
                "title": "Apply for LIHEAP — seasonal funds go fast",
                "detail": (
                    "LIHEAP funds are distributed on a first-come, first-served basis "
                    "each season and often run out. Apply as early as possible. "
                    "Also ask about weatherization assistance to permanently lower bills."
                ),
                "programs": ["LIHEAP"],
                "priority": 3,
            })

    # --- Rule 6: Lifeline + CARE stacking (CA) ---
    lifeline_eligible = "lifeline" in eligible_names
    care_eligible = "care" in eligible_names
    if lifeline_eligible and care_eligible:
        insights.append({
            "type": "efficiency",
            "title": "Stack Lifeline + CARE for maximum utility savings",
            "detail": (
                "You may qualify for both the Lifeline phone/internet discount AND "
                "the CARE energy discount. These are separate programs that stack — "
                "apply for both. Being approved for one often auto-qualifies you for "
                "the other."
            ),
            "programs": ["Lifeline", "CARE"],
            "priority": 3,
        })

    # --- Rule 7: SSI → automatic Medicaid in most states ---
    ssi_eligible = "ssi" in eligible_names
    if ssi_eligible and medicaid_eligible:
        insights.append({
            "type": "dependency",
            "title": "SSI approval automatically grants Medicaid in most states",
            "detail": (
                "In most states, being approved for SSI automatically enrolls you "
                "in Medicaid with no separate application needed. Focus on the SSI "
                "application first — Medicaid will follow."
            ),
            "programs": ["SSI", "Medicaid"],
            "priority": 2,
        })

    # --- Rule 8: Joint application efficiency ---
    if snap_eligible and medicaid_eligible:
        state = profile.get("state", "").upper()
        if state == "CA":
            insights.append({
                "type": "efficiency",
                "title": "Apply for CalFresh + Medi-Cal together on BenefitsCal.com",
                "detail": (
                    "California lets you apply for CalFresh, Medi-Cal, CalWORKs, and "
                    "CARE all through a single application at BenefitsCal.com. "
                    "One form, one submission — don't file separate applications."
                ),
                "programs": ["CalFresh", "Medi-Cal", "CalWORKs", "CARE"],
                "priority": 1,
            })

    # Sort by priority
    insights.sort(key=lambda x: x["priority"])
    return insights


def get_profile_gaps(profile: dict, eligible_programs: list[dict]) -> list[dict]:
    """Identify missing profile fields that could unlock additional benefits.

    Returns a list of dicts with:
        - field: the missing profile field name
        - question: a natural question to ask the user
        - reason: why this matters for eligibility
        - potential_programs: programs that could be affected
    """
    gaps: list[dict] = []

    # Housing status — needed for Section 8, LIHEAP, CARE
    if profile.get("housing_status") is None:
        gaps.append({
            "field": "housing_status",
            "question": "Are you currently renting, a homeowner, or in another housing situation? And roughly how much is your monthly rent or mortgage?",
            "reason": "This helps determine eligibility for housing assistance like Section 8 and utility programs like LIHEAP and CARE.",
            "potential_programs": ["Section 8", "LIHEAP", "CARE"],
        })

    # Health insurance — needed for Medicaid/CHIP
    if profile.get("has_health_insurance") is None:
        gaps.append({
            "field": "has_health_insurance",
            "question": "Do you currently have health insurance coverage?",
            "reason": "If you're uninsured, you may qualify for free coverage through Medicaid or CHIP for your children.",
            "potential_programs": ["Medicaid", "Medi-Cal", "CHIP"],
        })

    # Veteran status — unlocks VA benefits
    if profile.get("is_veteran") is None:
        gaps.append({
            "field": "is_veteran",
            "question": "Have you or anyone in your household served in the military?",
            "reason": "Veterans may qualify for additional VA benefits, healthcare, and housing assistance, and often get priority on Section 8 waitlists.",
            "potential_programs": ["Section 8", "VA Benefits"],
        })

    # Disability — needed for SSI, Section 8 priority
    if profile.get("is_disabled") is None:
        gaps.append({
            "field": "is_disabled",
            "question": "Does anyone in your household have a disability or chronic health condition that limits work?",
            "reason": "Disability status can qualify you for SSI cash assistance and gives priority on housing waitlists.",
            "potential_programs": ["SSI", "Section 8"],
        })

    # Pregnancy — needed for WIC
    if profile.get("is_pregnant") is None and profile.get("has_children") is not False:
        gaps.append({
            "field": "is_pregnant",
            "question": "Is anyone in the household currently pregnant?",
            "reason": "Pregnant women qualify for WIC nutrition benefits and may get enhanced Medicaid coverage.",
            "potential_programs": ["WIC", "Medicaid"],
        })

    # Children ages — needed for WIC, CHIP, Child Tax Credit
    if profile.get("has_children") and not profile.get("children_ages"):
        gaps.append({
            "field": "children_ages",
            "question": "How old are each of your children?",
            "reason": "Children's ages determine eligibility for WIC (under 5), CHIP (under 19), and Child Tax Credit (under 17).",
            "potential_programs": ["WIC", "CHIP", "Child Tax Credit"],
        })

    # Citizenship — needed for most federal programs
    if profile.get("is_citizen_or_legal_resident") is None:
        gaps.append({
            "field": "is_citizen_or_legal_resident",
            "question": "Are you a US citizen or legal permanent resident?",
            "reason": "Most federal benefit programs require citizenship or legal residency, though some state programs (like Medi-Cal in California) are available regardless of immigration status.",
            "potential_programs": ["SNAP", "Medicaid", "TANF", "Medi-Cal"],
        })

    # Employment — needed for EITC
    if profile.get("employment_status") is None:
        gaps.append({
            "field": "employment_status",
            "question": "What's your current employment situation — working full-time, part-time, self-employed, looking for work, or something else?",
            "reason": "Employment status determines EITC eligibility (requires earned income) and affects benefit amounts for several programs.",
            "potential_programs": ["EITC", "TANF", "CalWORKs"],
        })

    return gaps
