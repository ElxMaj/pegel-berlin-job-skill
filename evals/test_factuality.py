"""Factuality gate. These are the rules the skill exists to keep.

Every test here encodes a way a job-application tool is known to lie. The
salary/Blue-Card logic lives in code precisely so the model cannot "helpfully"
soften any of it. If one of these fails, the skill is no longer trustworthy and
must not ship.

Run:  python3 -m pytest evals/ -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pegel_query import blue_card, salary_text  # noqa: E402


def job(**over):
    base = {
        "salaryMin": None, "salaryMax": None, "salaryCurrency": None,
        "salaryPeriod": None, "languageTier": None, "visaTier": None, "techTags": [],
    }
    base.update(over)
    return base


# --- Never invent a salary -------------------------------------------------

def test_undisclosed_salary_is_reported_as_not_disclosed_not_as_a_range():
    # The #1 lie of AI job tools: turning "we don't know" into a plausible band.
    # An employer who did not publish pay must be reported as not having published pay.
    assert salary_text(job()) == "not disclosed"


def test_undisclosed_salary_never_becomes_a_number():
    out = salary_text(job())
    assert not any(ch.isdigit() for ch in out)


# --- Blue Card: a threshold comparison, never an optimistic verdict ---------

def test_blue_card_cannot_be_determined_without_a_disclosed_salary():
    # Refusing to answer is the correct answer. A candidate who relocates on a
    # guessed eligibility check pays for that guess with their visa.
    assert blue_card(job()) == "cannot be determined (salary not disclosed)"


def test_blue_card_uses_the_bottom_of_the_range_not_the_top():
    # The floor is the number the employer committed to. A tool that reads the
    # ceiling would tell a candidate on 45k-70k that they clear a 50.7k bar.
    # They do not.
    assert "below both" in blue_card(
        job(salaryMin=45_000, salaryMax=70_000, salaryCurrency="EUR", salaryPeriod="year")
    )


def test_blue_card_general_threshold_2026():
    assert "general threshold" in blue_card(
        job(salaryMin=50_700, salaryMax=60_000, salaryCurrency="EUR", salaryPeriod="year")
    )


def test_blue_card_shortage_threshold_2026():
    r = blue_card(job(salaryMin=46_000, salaryMax=48_000, salaryCurrency="EUR", salaryPeriod="year"))
    assert "shortage" in r and "general" not in r


def test_blue_card_one_euro_below_the_shortage_bar_is_below():
    # 45,934.20 is the bar. Twenty cents short is short. No rounding "to help".
    assert "below both" in blue_card(
        job(salaryMin=45_934, salaryCurrency="EUR", salaryPeriod="year")
    )


@pytest.mark.parametrize("period", ["month", "hour", "day"])
def test_blue_card_refuses_to_annualise_a_non_annual_salary(period):
    # Annualising needs an assumed working year. That is an estimate, and an
    # estimate is exactly what we refuse to make.
    assert "cannot be determined" in blue_card(
        job(salaryMin=5_000, salaryCurrency="EUR", salaryPeriod=period)
    )


def test_blue_card_refuses_to_convert_a_foreign_currency():
    # Converting at some exchange rate would invent a euro figure nobody published.
    assert "cannot be determined" in blue_card(
        job(salaryMin=90_000, salaryCurrency="USD", salaryPeriod="year")
    )


# --- Nulls stay unknown ----------------------------------------------------

def test_language_and_visa_nulls_map_to_unknown_not_to_no():
    from pegel_query import LANGUAGE, VISA
    # null means "Pegel could not determine this", NOT "no German needed" and
    # NOT "does not sponsor". Collapsing unknown into a negative is a lie that
    # costs the candidate real opportunities.
    assert LANGUAGE[None] == "unknown"
    assert VISA[None] == "unknown"
    assert VISA["does_not_sponsor"] != VISA[None]
