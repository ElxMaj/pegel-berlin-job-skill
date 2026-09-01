#!/usr/bin/env python3
"""Query Pegel's public job API. The job list is the skill's only source of roles.

Deterministic on purpose: the querying, the null-handling and the Blue Card
threshold comparison are done in code, so the model cannot "helpfully" fill a
missing salary or round a threshold. If Pegel does not know, this prints unknown.

Usage:
  python3 scripts/pegel_query.py --german not_needed --salary-disclosed --limit 10
  python3 scripts/pegel_query.py --tech-tags react,typescript --seniority senior
  python3 scripts/pegel_query.py --q "platform engineer" --json
  python3 scripts/pegel_query.py --mark-json-stdin
  python3 scripts/pegel_query.py --list-decisions shortlisted
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from job_decisions import (
    DecisionStoreCommittedError,
    DecisionStoreError,
    STATUSES,
    chronological_history,
    decision_path,
    forget_decision,
    get_decision,
    is_trusted_pegel_url,
    list_decisions,
    load_decisions,
    normalize_job_id,
    record_decision,
    validate_event_input,
    validate_job_snapshot,
)

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
MARK_STDIN_MAX_BYTES = 16 * 1024
MARK_STDIN_FIELDS = {
    "jobId",
    "status",
    "date",
    "note",
    "rejectionReason",
    "responseKind",
    "contactName",
}


class PegelApiError(RuntimeError):
    """A read from Pegel's public API failed or returned an invalid shape."""


def _read_mark_json_stdin(stdin) -> dict:
    try:
        raw_payload = stdin.read(MARK_STDIN_MAX_BYTES + 1)
    except (OSError, UnicodeError) as error:
        raise DecisionStoreError("Could not read mark JSON from stdin") from error
    if not isinstance(raw_payload, str):
        raise DecisionStoreError("Mark JSON stdin must be text")
    try:
        payload_size = len(raw_payload.encode("utf-8"))
    except UnicodeError as error:
        raise DecisionStoreError("Mark JSON stdin is not valid UTF-8 text") from error
    if payload_size > MARK_STDIN_MAX_BYTES:
        raise DecisionStoreError("Mark JSON stdin is too large")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DecisionStoreError("Mark stdin must contain one valid JSON object") from error
    if not isinstance(payload, dict):
        raise DecisionStoreError("Mark stdin must contain one JSON object")
    unknown = set(payload) - MARK_STDIN_FIELDS
    if unknown:
        raise DecisionStoreError("Mark JSON has unknown fields")
    missing = {"jobId", "status"} - set(payload)
    if missing:
        raise DecisionStoreError(
            f"Mark JSON is missing required field: {', '.join(sorted(missing))}"
        )
    null_fields = [field for field, value in payload.items() if value is None]
    if null_fields:
        raise DecisionStoreError(
            f"Mark JSON fields may not be null: {', '.join(sorted(null_fields))}"
        )
    return payload


@dataclass(frozen=True)
class SearchResult:
    jobs: list[dict]
    api_total_count: int
    scanned: int
    decided_excluded: int
    pages_fetched: int


def _fetch_json(url: str, *, allow_not_found: bool = False) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404 and allow_not_found:
            return None
        if e.code == 429:
            raise PegelApiError("Rate limited by Pegel (60 req/min). Wait a minute and retry.") from e
        raise PegelApiError(f"Pegel API error {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise PegelApiError(f"Could not reach Pegel: {e.reason}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise PegelApiError("Pegel response could not be read. Retry in a minute.") from e
    except json.JSONDecodeError:
        # A 200 with a non-JSON body (proxy error page, captive portal) should
        # fail as cleanly as a network error, not as a traceback.
        raise PegelApiError("Pegel returned a response that is not valid JSON. Retry in a minute.")


def fetch(params: dict[str, str]) -> dict:
    payload = _fetch_json(f"{API}?{urllib.parse.urlencode(params)}")
    if not isinstance(payload, dict):
        raise PegelApiError("Pegel returned an invalid job-list response")
    return payload


def _validated_fetched_job(job: object, job_id: str) -> dict | None:
    if job is None:
        return None
    if not isinstance(job, dict) or job.get("id") != job_id:
        raise PegelApiError("Pegel returned an invalid job response")
    try:
        validate_job_snapshot(job)
    except DecisionStoreError as error:
        raise PegelApiError("Pegel returned an invalid job snapshot") from error
    return job


def fetch_job(job_id: str) -> dict | None:
    job_id = normalize_job_id(job_id)
    url = f"{API}/{urllib.parse.quote(job_id, safe='')}"
    payload = _fetch_json(url, allow_not_found=True)
    if payload is None:
        return None
    job = payload.get("data") if isinstance(payload, dict) else None
    return _validated_fetched_job(job, job_id)


def collect_jobs(
    params: dict[str, str],
    *,
    limit: int,
    decided_ids: set[str],
    include_decided: bool = False,
    fetch_page: Callable[[dict[str, str]], dict] = fetch,
) -> SearchResult:
    jobs: list[dict] = []
    scanned = 0
    decided_excluded = 0
    page = 1
    api_total_count = 0
    seen_job_ids: set[str] = set()

    while len(jobs) < limit:
        page_params = {**params, "page": str(page), "pageSize": "100"}
        payload = fetch_page(page_params)
        page_jobs = payload.get("data") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if (
            not isinstance(page_jobs, list)
            or not all(isinstance(job, dict) for job in page_jobs)
            or not isinstance(pagination, dict)
            or not isinstance(pagination.get("totalCount"), int)
            or not isinstance(pagination.get("totalPages"), int)
        ):
            raise PegelApiError("Pegel returned an invalid job-list response")
        api_total_count = pagination["totalCount"]

        for job in page_jobs:
            scanned += 1
            try:
                job_id = normalize_job_id(job.get("id"))
            except DecisionStoreError as error:
                raise PegelApiError("Pegel returned a job with an invalid job ID") from error
            if job_id in seen_job_ids:
                continue
            seen_job_ids.add(job_id)
            if not include_decided and job_id in decided_ids:
                decided_excluded += 1
                continue
            jobs.append(job)
            if len(jobs) == limit:
                break

        total_pages = pagination["totalPages"]
        if not page_jobs or page >= total_pages:
            break
        page += 1

    return SearchResult(jobs, api_total_count, scanned, decided_excluded, page)


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(payload: dict, stdout) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stdout)


def _status_text(status: str) -> str:
    if status == "passed":
        return "passed (you chose not to pursue this role)"
    return status


def _write_text_field(label: str, value: object, stdout, *, indent: str = "  ") -> None:
    text = str(value)
    prefix = f"{indent}{label:<9}: "
    continuation = " " * len(prefix)
    lines = text.split("\n")
    print(f"{prefix}{lines[0]}", file=stdout)
    for line in lines[1:]:
        print(f"{continuation}{line}", file=stdout)


def _write_decision_summary(item: dict, stdout) -> None:
    _write_text_field("Role", item.get("title") or "Unknown role", stdout)
    _write_text_field("Company", item.get("company") or "unknown company", stdout)
    _write_text_field("Status", _status_text(item["status"]), stdout)
    _write_text_field("Updated", item.get("updatedAt") or "unknown", stdout)
    _write_text_field("Job ID", item["id"], stdout)
    if item.get("pegelUrl"):
        _write_text_field("Read", item["pegelUrl"], stdout)


def _write_history(record: dict, stdout) -> None:
    _write_decision_summary(record, stdout)
    print("\nTimeline", file=stdout)
    for event in chronological_history(record["history"]):
        _write_text_field("Date", event["date"], stdout)
        _write_text_field("Status", _status_text(event["status"]), stdout)
        _write_text_field("Recorded", event["recordedAt"], stdout)
        for field, label in (
            ("note", "Note"),
            ("rejectionReason", "Reason"),
            ("responseKind", "Response"),
            ("contactName", "Contact"),
        ):
            if field in event:
                _write_text_field(label, event[field], stdout)
        print(file=stdout)


def main(
    argv: list[str] | None = None,
    *,
    fetch_page: Callable[[dict[str, str]], dict] | None = None,
    fetch_detail: Callable[[str], dict | None] | None = None,
    now: Callable[[], str] = utc_now,
    stdin=sys.stdin,
    stdout=sys.stdout,
    stderr=sys.stderr,
) -> int:
    p = argparse.ArgumentParser(description="Search live Berlin startup jobs on Pegel.")
    p.add_argument(
        "--state-file",
        type=Path,
        help="override the local decision file (also PEGEL_DECISIONS_FILE)",
    )
    decision_actions = p.add_mutually_exclusive_group()
    decision_actions.add_argument(
        "--mark",
        nargs=2,
        metavar=("JOB_ID", "STATUS"),
        help=(
            "append a status event using direct CLI compatibility inputs; values may be "
            "visible in child argv and shell history"
        ),
    )
    decision_actions.add_argument(
        "--mark-json-stdin",
        action="store_true",
        help="read one private mark from stdin without putting its values in child argv",
    )
    decision_actions.add_argument(
        "--list-decisions",
        choices=("all", *STATUSES),
        help="list saved decisions locally without an API request",
    )
    decision_actions.add_argument(
        "--history",
        metavar="JOB_ID",
        help="show one saved decision timeline without an API request",
    )
    decision_actions.add_argument(
        "--forget",
        metavar="JOB_ID",
        help="delete one decision so the role appears in normal searches again",
    )
    p.add_argument("--date", help="event date in YYYY-MM-DD format (mark only)")
    p.add_argument("--note", help="short local note (mark only)")
    p.add_argument("--reason", help="short rejection reason (rejected mark only)")
    p.add_argument("--response-kind", help="human, automated or unknown (mark only)")
    p.add_argument("--contact-name", help="contact name (mark only)")
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
    p.add_argument(
        "--include-decided",
        action="store_true",
        help="include roles with any saved status",
    )
    p.add_argument("--json", action="store_true", help="locally filtered JSON")
    a = p.parse_args(argv)

    state_file = decision_path(a.state_file)
    metadata = (a.date, a.note, a.reason, a.response_kind, a.contact_name)
    if a.mark_json_stdin and any(value is not None for value in metadata):
        print(
            "Decision error: --mark-json-stdin conflicts with legacy metadata flags",
            file=stderr,
        )
        return 2
    if any(value is not None for value in metadata) and not a.mark:
        print("Decision error: Event metadata may only be used with --mark", file=stderr)
        return 2
    if a.mark or a.mark_json_stdin:
        try:
            if a.mark_json_stdin:
                mark = _read_mark_json_stdin(stdin)
                job_id = mark["jobId"]
                status = mark["status"]
                event_date = mark.get("date")
                note = mark.get("note")
                reason = mark.get("rejectionReason")
                response_kind = mark.get("responseKind")
                contact_name = mark.get("contactName")
            else:
                job_id, status = a.mark
                event_date = a.date
                note = a.note
                reason = a.reason
                response_kind = a.response_kind
                contact_name = a.contact_name
            job_id = normalize_job_id(job_id)
            recorded_at = now()
            event = validate_event_input(
                status,
                recorded_at,
                event_date,
                note,
                reason,
                response_kind,
                contact_name,
            )
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 2
        try:
            job = _validated_fetched_job((fetch_detail or fetch_job)(job_id), job_id)
        except PegelApiError as error:
            job = None
            print(f"Warning: {error}; saved without a job snapshot.", file=stderr)
        try:
            record = record_decision(
                state_file,
                job_id,
                status,
                job=job,
                now=recorded_at,
                event_date=event["date"],
                note=note,
                rejection_reason=reason,
                response_kind=response_kind,
                contact_name=contact_name,
            )
        except DecisionStoreCommittedError as error:
            record = error.committed_result
            print(
                "Warning: Change was saved, but decision-lock cleanup failed. "
                "Inspect local history before attempting another update.",
                file=stderr,
            )
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 2
        if a.json:
            _write_json({"data": record}, stdout)
        else:
            print(f"Marked {job_id} as {_status_text(status)}. Saved locally in {state_file}", file=stdout)
        return 0
    if a.list_decisions:
        status = None if a.list_decisions == "all" else a.list_decisions
        try:
            saved = list_decisions(state_file, status)
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 1
        label = a.list_decisions
        if a.json:
            _write_json(
                {
                    "data": saved,
                    "selection": {"status": label, "returned": len(saved)},
                },
                stdout,
            )
            return 0
        noun = "role" if len(saved) == 1 else "roles"
        print(f"{len(saved)} {label} {noun}\n", file=stdout)
        for item in saved:
            _write_decision_summary(item, stdout)
            print(file=stdout)
        return 0
    if a.history:
        try:
            job_id = normalize_job_id(a.history)
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 2
        try:
            record = get_decision(state_file, job_id)
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 1
        if record is None:
            print(f"No local history exists for {job_id}.", file=stderr)
            return 1
        record["history"] = chronological_history(record["history"])
        if a.json:
            _write_json({"data": record}, stdout)
        else:
            _write_history(record, stdout)
        return 0
    if a.forget:
        try:
            job_id = normalize_job_id(a.forget)
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 2
        try:
            removed = forget_decision(state_file, job_id)
        except DecisionStoreCommittedError as error:
            removed = error.committed_result
            print(
                "Warning: Change was saved, but decision-lock cleanup failed. "
                "Inspect local history before attempting another update.",
                file=stderr,
            )
        except DecisionStoreError as error:
            print(f"Decision error: {error}", file=stderr)
            return 1
        if a.json:
            _write_json({"data": {"id": job_id, "forgotten": removed}}, stdout)
            return 0
        if removed:
            print(f"Forgot {job_id}. It will appear in normal searches again.", file=stdout)
        else:
            print(f"No local decision exists for {job_id}.", file=stdout)
        return 0

    limit = min(max(a.limit, 1), 100)
    params: dict[str, str] = {}
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

    try:
        decisions = load_decisions(state_file)["jobs"]
        result = collect_jobs(
            params,
            limit=limit,
            decided_ids=set(decisions),
            include_decided=a.include_decided,
            fetch_page=fetch_page or fetch,
        )
    except (DecisionStoreError, PegelApiError) as error:
        print(f"Error: {error}", file=stderr)
        return 1
    jobs = result.jobs

    if a.json:
        _write_json(
            {
                "data": jobs,
                "pagination": {
                    "page": 1,
                    "pageSize": limit,
                    "totalCount": result.api_total_count,
                    "totalPages": (result.api_total_count + limit - 1) // limit,
                },
                "selection": {
                    "returned": len(jobs),
                    "apiMatches": result.api_total_count,
                    "scanned": result.scanned,
                    "decidedExcluded": result.decided_excluded,
                    "decidedFiltering": not a.include_decided,
                },
            },
            stdout,
        )
        return 0

    qualifier = "matching" if a.include_decided else "unseen"
    print(f"{len(jobs)} {qualifier} of {result.api_total_count} matching roles", file=stdout)
    if result.decided_excluded:
        print(f"{result.decided_excluded} decided roles skipped while scanning", file=stdout)
    print(file=stdout)
    for j in jobs:
        # Defensive .get() throughout: one malformed record must not abort the
        # whole listing with a KeyError.
        company = (j.get("company") or {}).get("name") or "unknown company"
        print(f"{j.get('title') or 'Untitled role'} — {company}", file=stdout)
        print(f"  Job ID     : {j.get('id') or 'unknown'}", file=stdout)
        print(f"  Location   : {j.get('location') or 'unknown'}", file=stdout)
        print(f"  German     : {LANGUAGE.get(j.get('languageTier'), 'unknown')}", file=stdout)
        print(f"  Visa       : {VISA.get(j.get('visaTier'), 'unknown')}", file=stdout)
        print(f"  Salary     : {salary_text(j)}", file=stdout)
        print(f"  Blue Card  : {blue_card(j)}", file=stdout)
        tags = j.get("techTags") or []
        print(f"  Stack      : {', '.join(tags) if tags else 'no stack signal'}", file=stdout)
        print(f"  Last seen  : {j.get('lastSeenAt', 'unknown')}", file=stdout)
        # Only surface a link that is actually Pegel's. A tampered or malformed
        # response must not plant an arbitrary URL under a trusted label.
        url = j.get("pegelUrl") or ""
        if is_trusted_pegel_url(url):
            print(f"  Read/apply : {url}", file=stdout)
        else:
            print("  Read/apply : unknown (no Pegel link in this record)", file=stdout)
        print(file=stdout)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
