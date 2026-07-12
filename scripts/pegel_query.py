#!/usr/bin/env python3
"""Query Pegel's public job API. The job list is the skill's only source of roles.

Deterministic on purpose: the querying, the null-handling and the Blue Card
threshold comparison are done in code, so the model cannot "helpfully" fill a
missing salary or round a threshold. If Pegel does not know, this prints unknown.

Usage:
  python3 scripts/pegel_query.py --german not_needed --salary-disclosed --limit 10
  python3 scripts/pegel_query.py --tech-tags react,typescript --seniority senior
  python3 scripts/pegel_query.py --q "platform engineer" --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://pegel.berlin/api/v1/jobs"
UA = "pegel-berlin-job-skill (+https://github.com/ElxMaj/pegel-berlin-job-skill)"

# EU Blue Card 2026 annual gross minimums (Germany).
# Source: Make it in Germany. Thresholds change annually — see
# references/germany-immigration.md for the review date.
BLUE_CARD_2026_GENERAL = 50_700
BLUE_CARD_2026_SHORTAGE = 45_934.20

# languageTier (response) -> plain English. null is a real answer: "we don't know".
LANGUAGE = {"none": "No German required", "required": "German required", None: "unknown"}
VISA = {"sponsors": "Sponsors visas", "does_not_sponsor": "Does not sponsor", None: "unknown"}


def fetch(params: dict[str, str]) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            sys.exit("Rate limited by Pegel (60 req/min). Wait a minute and retry.")
        sys.exit(f"Pegel API error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach Pegel: {e.reason}")


def salary_text(j: dict) -> str:
    """Employer-disclosed pay only. Never estimated, never inferred."""
    lo, hi, cur, per = j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency"), j.get("salaryPeriod")
    if lo is None and hi is None:
        return "not disclosed"
    cur = cur or ""
    per = f"/{per}" if per else ""
    if lo is not None and hi is not None and lo != hi:
        return f"{lo:,}-{hi:,} {cur}{per}".strip()
    return f"{(lo if lo is not None else hi):,} {cur}{per}".strip()


def blue_card(j: dict) -> str:
    """Compare disclosed annual gross to the 2026 thresholds.

    This is a SALARY-THRESHOLD COMPARISON, not a visa verdict: a Blue Card also
    needs a recognised degree and a matching offer. Anything we cannot verify
    stays 'cannot be determined' rather than becoming an optimistic guess.
    """
    lo, cur, per = j.get("salaryMin"), j.get("salaryCurrency"), j.get("salaryPeriod")
    if lo is None:
        return "cannot be determined (salary not disclosed)"
    if cur != "EUR":
        return f"cannot be determined (salary is in {cur}, thresholds are in EUR)"
    if per != "year":
        return f"cannot be determined (salary is per {per}, thresholds are annual)"
    # Compare the BOTTOM of the range: that is the number the employer committed to.
    if lo >= BLUE_CARD_2026_GENERAL:
        return f"meets the general threshold (>= {BLUE_CARD_2026_GENERAL:,} EUR)"
    if lo >= BLUE_CARD_2026_SHORTAGE:
        return f"meets the shortage/graduate threshold (>= {BLUE_CARD_2026_SHORTAGE:,.2f} EUR) only"
    return f"below both 2026 thresholds (< {BLUE_CARD_2026_SHORTAGE:,.2f} EUR)"


def main() -> None:
    p = argparse.ArgumentParser(description="Search live Berlin startup jobs on Pegel.")
    p.add_argument("--german", choices=["not_needed", "needed", "unknown"])
    p.add_argument("--visa", action="store_true", help="Company-level sponsorship signal")
    p.add_argument("--salary-disclosed", action="store_true")
    p.add_argument("--tech-tags")
    p.add_argument("--seniority")
    p.add_argument("--contract")
    p.add_argument("--sector")
    p.add_argument("--company")
    p.add_argument("--posted-within", choices=["7d", "30d", "90d", "all"])
    p.add_argument("--q")
    p.add_argument("--limit", type=int, default=10, help="max 100")
    p.add_argument("--json", action="store_true", help="raw JSON")
    a = p.parse_args()

    params: dict[str, str] = {"pageSize": str(min(max(a.limit, 1), 100))}
    if a.german:
        params["german"] = a.german
    if a.visa:
        params["visa"] = "1"
    if a.salary_disclosed:
        params["salaryDisclosed"] = "1"
    for key, val in (
        ("techTags", a.tech_tags), ("seniority", a.seniority), ("contract", a.contract),
        ("sector", a.sector), ("company", a.company), ("postedWithin", a.posted_within), ("q", a.q),
    ):
        if val:
            params[key] = val

    payload = fetch(params)
    jobs = payload.get("data", [])

    if a.json:
        print(json.dumps(payload, indent=2))
        return

    total = payload.get("pagination", {}).get("totalCount", len(jobs))
    print(f"{len(jobs)} of {total} matching roles\n")
    for j in jobs:
        print(f"{j['title']} — {j['company']['name']}")
        print(f"  Location   : {j.get('location') or 'unknown'}")
        print(f"  German     : {LANGUAGE.get(j.get('languageTier'), 'unknown')}")
        print(f"  Visa       : {VISA.get(j.get('visaTier'), 'unknown')}")
        print(f"  Salary     : {salary_text(j)}")
        print(f"  Blue Card  : {blue_card(j)}")
        tags = j.get("techTags") or []
        print(f"  Stack      : {', '.join(tags) if tags else 'no stack signal'}")
        print(f"  Last seen  : {j.get('lastSeenAt', 'unknown')}")
        print(f"  Read/apply : {j['pegelUrl']}")
        print()


if __name__ == "__main__":
    main()
