"""Private, local job-decision history for the Pegel skill."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


SCHEMA_VERSION = 2
STATUSES = (
    "shortlisted",
    "applied",
    "interviewing",
    "offered",
    "accepted",
    "rejected",
    "withdrawn",
    "passed",
)
VERDICTS = STATUSES
RESPONSE_KINDS = ("human", "automated", "unknown")

_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EVENT_FIELDS = {
    "status",
    "date",
    "recordedAt",
    "note",
    "rejectionReason",
    "responseKind",
    "contactName",
}
_RECORD_FIELDS = {"status", "updatedAt", "history", "title", "company", "pegelUrl"}


class DecisionStoreError(ValueError):
    """The local decision file or requested update is invalid."""


def decision_path(override: Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser()
    configured = os.environ.get("PEGEL_DECISIONS_FILE")
    if configured:
        return Path(configured).expanduser()
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "pegel" / "job-decisions.json"


def normalize_job_id(job_id: str) -> str:
    try:
        return str(UUID(job_id))
    except (ValueError, AttributeError, TypeError) as error:
        raise DecisionStoreError("Job ID must be a full Pegel job UUID") from error


def is_trusted_pegel_url(value: object) -> bool:
    if not isinstance(value, str) or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc == "pegel.berlin"
        and parsed.path.startswith("/")
    )


def _empty_store() -> dict:
    return {"version": SCHEMA_VERSION, "jobs": {}}


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise DecisionStoreError(f"Decision file has an invalid {field}")
    try:
        return datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise DecisionStoreError(f"Decision file has an invalid {field}") from error


def _parse_event_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise DecisionStoreError("Decision file has an invalid date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise DecisionStoreError("Decision file has an invalid date") from error


def _validate_optional_text(value: object, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise DecisionStoreError(f"Decision file has an invalid {field}")
    if any(character not in "\n\t" and unicodedata.category(character).startswith("C") for character in value):
        raise DecisionStoreError(f"Decision file has an invalid {field}")
    return value


def _validate_snapshot(record: dict, job_id: str) -> None:
    for field in ("title", "company"):
        if field in record:
            _validate_optional_text(record[field], field, 200)
    if "pegelUrl" in record and record["pegelUrl"] is not None and not is_trusted_pegel_url(record["pegelUrl"]):
        raise DecisionStoreError(f"Decision file has an invalid pegelUrl for {job_id}")


def _validate_event(event: object, job_id: str) -> dict:
    if not isinstance(event, dict) or set(event) - _EVENT_FIELDS:
        raise DecisionStoreError(f"Decision file has an invalid event for {job_id}")
    if event.get("status") not in STATUSES:
        raise DecisionStoreError(f"Decision file has an invalid status for {job_id}")
    _parse_event_date(event.get("date"))
    _parse_utc_timestamp(event.get("recordedAt"), "recordedAt")
    _validate_optional_text(event.get("note"), "note", 4000)
    _validate_optional_text(event.get("contactName"), "contactName", 200)
    if event.get("responseKind") is not None and event["responseKind"] not in RESPONSE_KINDS:
        raise DecisionStoreError(f"Decision file has an invalid responseKind for {job_id}")

    reason = _validate_optional_text(event.get("rejectionReason"), "rejectionReason", 1000)
    if event["status"] == "rejected" and reason is None:
        raise DecisionStoreError(f"Decision file has an invalid rejectionReason for {job_id}")
    if event["status"] != "rejected" and "rejectionReason" in event:
        raise DecisionStoreError(f"Decision file has an invalid rejectionReason for {job_id}")
    return copy.deepcopy(event)


def _current_event(history: list[dict]) -> dict:
    return max(
        enumerate(history),
        key=lambda item: (
            _parse_event_date(item[1]["date"]),
            _parse_utc_timestamp(item[1]["recordedAt"], "recordedAt"),
            item[0],
        ),
    )[1]


def _normalize_v1(store: object) -> dict:
    if not isinstance(store, dict) or type(store.get("version")) is not int or store["version"] != 1:
        raise DecisionStoreError("Decision file has an unsupported schema version")
    jobs = store.get("jobs")
    if not isinstance(jobs, dict):
        raise DecisionStoreError("Decision file jobs must be an object")

    normalized = _empty_store()
    for job_id, decision in jobs.items():
        if normalize_job_id(job_id) != job_id:
            raise DecisionStoreError(f"Decision file has an invalid job ID: {job_id}")
        if not isinstance(decision, dict) or decision.get("verdict") not in STATUSES:
            raise DecisionStoreError(f"Decision file has an invalid verdict for {job_id}")
        recorded_at = decision.get("updatedAt")
        _parse_utc_timestamp(recorded_at, "updatedAt")
        _validate_snapshot(decision, job_id)
        record = {
            "status": decision["verdict"],
            "updatedAt": recorded_at,
            "history": [
                {
                    "status": decision["verdict"],
                    "date": recorded_at[:10],
                    "recordedAt": recorded_at,
                }
            ],
        }
        for field in ("title", "company", "pegelUrl"):
            if field in decision:
                record[field] = copy.deepcopy(decision[field])
        normalized["jobs"][job_id] = record
    return normalized


def _validate_v2(store: object) -> dict:
    if not isinstance(store, dict) or type(store.get("version")) is not int or store["version"] != SCHEMA_VERSION:
        raise DecisionStoreError("Decision file has an unsupported schema version")
    jobs = store.get("jobs")
    if not isinstance(jobs, dict):
        raise DecisionStoreError("Decision file jobs must be an object")

    validated = _empty_store()
    for job_id, record in jobs.items():
        if normalize_job_id(job_id) != job_id:
            raise DecisionStoreError(f"Decision file has an invalid job ID: {job_id}")
        if not isinstance(record, dict) or set(record) - _RECORD_FIELDS:
            raise DecisionStoreError(f"Decision file has an invalid record for {job_id}")
        if record.get("status") not in STATUSES:
            raise DecisionStoreError(f"Decision file has an invalid status for {job_id}")
        _parse_utc_timestamp(record.get("updatedAt"), "updatedAt")
        history = record.get("history")
        if not isinstance(history, list) or not history:
            raise DecisionStoreError(f"Decision file has an invalid history for {job_id}")
        validated_history = [_validate_event(event, job_id) for event in history]
        if record["status"] != _current_event(validated_history)["status"]:
            raise DecisionStoreError(f"Decision file has an invalid status for {job_id}")
        _validate_snapshot(record, job_id)
        validated_record = {
            "status": record["status"],
            "updatedAt": record["updatedAt"],
            "history": validated_history,
        }
        for field in ("title", "company", "pegelUrl"):
            if field in record:
                validated_record[field] = copy.deepcopy(record[field])
        validated["jobs"][job_id] = validated_record
    return validated


def load_decisions(path: Path) -> dict:
    if not path.exists():
        return _empty_store()
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecisionStoreError(f"Decision file is not valid JSON: {path}") from error
    if not isinstance(store, dict) or type(store.get("version")) is not int:
        raise DecisionStoreError("Decision file has an unsupported schema version")
    if store["version"] == 1:
        return _validate_v2(_normalize_v1(store))
    return _validate_v2(store)


def _write_store(path: Path, store: dict) -> None:
    parent_created = not path.parent.exists()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent_created:
        os.chmod(path.parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _event_input(
    status: str,
    now: object,
    event_date: object | None,
    note: object,
    rejection_reason: object,
    response_kind: object,
    contact_name: object,
) -> dict:
    if status not in STATUSES:
        raise DecisionStoreError(f"Status must be one of: {', '.join(STATUSES)}")
    recorded_at = _parse_utc_timestamp(now, "recordedAt")
    if event_date is None:
        event_date = recorded_at.date().isoformat()
    _parse_event_date(event_date)
    event = {"status": status, "date": event_date, "recordedAt": now}
    for field, value, limit in (
        ("note", note, 4000),
        ("contactName", contact_name, 200),
    ):
        if value is not None:
            event[field] = _validate_optional_text(value, field, limit)
    if response_kind is not None:
        if response_kind not in RESPONSE_KINDS:
            raise DecisionStoreError("Decision file has an invalid responseKind")
        event["responseKind"] = response_kind
    if rejection_reason is not None:
        event["rejectionReason"] = _validate_optional_text(rejection_reason, "rejectionReason", 1000)
    return _validate_event(event, "new decision")


def _snapshot_from_job(job: object, existing: dict) -> dict:
    snapshot = {
        field: copy.deepcopy(existing[field])
        for field in ("title", "company", "pegelUrl")
        if field in existing
    }
    if job is None:
        return snapshot
    if not isinstance(job, dict):
        raise DecisionStoreError("Decision file has an invalid job")
    if "title" in job and job["title"] is not None:
        snapshot["title"] = _validate_optional_text(job["title"], "title", 200)
    if "company" in job and job["company"] is not None:
        company = job["company"]
        if not isinstance(company, dict):
            raise DecisionStoreError("Decision file has an invalid company")
        if "name" in company and company["name"] is not None:
            snapshot["company"] = _validate_optional_text(company["name"], "company", 200)
    if "pegelUrl" in job and job["pegelUrl"] is not None:
        if not is_trusted_pegel_url(job["pegelUrl"]):
            raise DecisionStoreError("Decision file has an invalid pegelUrl")
        snapshot["pegelUrl"] = job["pegelUrl"]
    return snapshot


def record_decision(
    path: Path,
    job_id: str,
    status: str,
    *,
    job: dict | None,
    now: str,
    event_date: str | None = None,
    note: str | None = None,
    rejection_reason: str | None = None,
    response_kind: str | None = None,
    contact_name: str | None = None,
) -> dict:
    job_id = normalize_job_id(job_id)
    event = _event_input(
        status,
        now,
        event_date,
        note,
        rejection_reason,
        response_kind,
        contact_name,
    )
    store = load_decisions(path)
    existing = store["jobs"].get(job_id, {})
    snapshot = _snapshot_from_job(job, existing)
    history = [*existing.get("history", []), event]
    record = {
        "status": _current_event(history)["status"],
        "updatedAt": now,
        "history": history,
        **snapshot,
    }
    store["jobs"][job_id] = record
    _write_store(path, store)
    return {"id": job_id, **copy.deepcopy(record)}


def get_decision(path: Path, job_id: str) -> dict | None:
    job_id = normalize_job_id(job_id)
    record = load_decisions(path)["jobs"].get(job_id)
    if record is None:
        return None
    return {"id": job_id, **copy.deepcopy(record)}


def list_decisions(path: Path, status: str | None = None) -> list[dict]:
    if status is not None and status not in STATUSES:
        raise DecisionStoreError(f"Status must be one of: {', '.join(STATUSES)}")
    selected = [
        {"id": job_id, **copy.deepcopy(record), "verdict": record["status"]}
        for job_id, record in load_decisions(path)["jobs"].items()
        if status is None or record["status"] == status
    ]
    return sorted(selected, key=lambda item: item["updatedAt"], reverse=True)


def forget_decision(path: Path, job_id: str) -> bool:
    job_id = normalize_job_id(job_id)
    store = load_decisions(path)
    if job_id not in store["jobs"]:
        return False
    del store["jobs"][job_id]
    _write_store(path, store)
    return True
