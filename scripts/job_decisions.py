"""Private, local job decisions for the Pegel skill."""
from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


SCHEMA_VERSION = 1
VERDICTS = ("shortlisted", "applied", "passed")


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


def load_decisions(path: Path) -> dict:
    if not path.exists():
        return _empty_store()
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecisionStoreError(f"Decision file is not valid JSON: {path}") from error
    if (
        not isinstance(store, dict)
        or type(store.get("version")) is not int
        or store["version"] != SCHEMA_VERSION
    ):
        raise DecisionStoreError("Decision file has an unsupported schema version")
    jobs = store.get("jobs")
    if not isinstance(jobs, dict):
        raise DecisionStoreError("Decision file jobs must be an object")
    for job_id, decision in jobs.items():
        if normalize_job_id(job_id) != job_id:
            raise DecisionStoreError(f"Decision file has an invalid job ID: {job_id}")
        if not isinstance(decision, dict) or decision.get("verdict") not in VERDICTS:
            raise DecisionStoreError(f"Decision file has an invalid verdict for {job_id}")
        if not isinstance(decision.get("updatedAt"), str):
            raise DecisionStoreError(f"Decision file has an invalid updatedAt for {job_id}")
        for field in ("title", "company"):
            if decision.get(field) is not None and not isinstance(decision.get(field), str):
                raise DecisionStoreError(f"Decision file has an invalid {field} for {job_id}")
        pegel_url = decision.get("pegelUrl")
        if pegel_url is not None and not is_trusted_pegel_url(pegel_url):
            raise DecisionStoreError(f"Decision file has an invalid pegelUrl for {job_id}")
    return store


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


def record_decision(
    path: Path,
    job_id: str,
    verdict: str,
    *,
    job: dict | None,
    now: str,
) -> None:
    if verdict not in VERDICTS:
        raise DecisionStoreError(f"Verdict must be one of: {', '.join(VERDICTS)}")
    job_id = normalize_job_id(job_id)
    store = load_decisions(path)
    existing = store["jobs"].get(job_id, {})
    title = job.get("title") if job else existing.get("title")
    if not isinstance(title, str):
        title = existing.get("title") if isinstance(existing.get("title"), str) else None
    company = (job.get("company") or {}).get("name") if job and isinstance(job.get("company"), dict) else None
    if not isinstance(company, str):
        company = existing.get("company") if isinstance(existing.get("company"), str) else None
    pegel_url = job.get("pegelUrl") if job else existing.get("pegelUrl")
    if not is_trusted_pegel_url(pegel_url):
        existing_url = existing.get("pegelUrl")
        pegel_url = existing_url if is_trusted_pegel_url(existing_url) else None
    store["jobs"][job_id] = {
        "verdict": verdict,
        "updatedAt": now,
        "title": title,
        "company": company,
        "pegelUrl": pegel_url,
    }
    _write_store(path, store)


def list_decisions(path: Path, verdict: str | None = None) -> list[dict]:
    if verdict is not None and verdict not in VERDICTS:
        raise DecisionStoreError(f"Verdict must be one of: {', '.join(VERDICTS)}")
    jobs = load_decisions(path)["jobs"]
    selected = [
        {"id": job_id, **decision}
        for job_id, decision in jobs.items()
        if verdict is None or decision["verdict"] == verdict
    ]
    return sorted(selected, key=lambda item: item.get("updatedAt", ""), reverse=True)


def forget_decision(path: Path, job_id: str) -> bool:
    job_id = normalize_job_id(job_id)
    store = load_decisions(path)
    if job_id not in store["jobs"]:
        return False
    del store["jobs"][job_id]
    _write_store(path, store)
    return True
