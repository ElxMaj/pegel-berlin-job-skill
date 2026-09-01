"""Private, local job-decision history for the Pegel skill."""
from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
import unicodedata
from contextlib import contextmanager
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
_STORE_FIELDS = {"version", "jobs"}
_RECORD_FIELDS = {"status", "updatedAt", "history", "title", "company", "pegelUrl"}


class DecisionStoreError(ValueError):
    """The local decision file or requested update is invalid."""


class DecisionStoreCommittedError(DecisionStoreError):
    """The requested mutation committed, but descriptor cleanup failed."""

    def __init__(self, message: str, committed_result: object):
        super().__init__(message)
        self.committed_result = copy.deepcopy(committed_result)


class _StoreLockState:
    def __init__(self) -> None:
        self.committed = False
        self.committed_result = None

    def mark_committed(self, result: object) -> None:
        self.committed = True
        self.committed_result = copy.deepcopy(result)


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
    for field, limit in (("note", 4000), ("contactName", 200)):
        if field in event:
            if event[field] is None:
                raise DecisionStoreError(f"Decision file has an invalid {field} for {job_id}")
            _validate_optional_text(event[field], field, limit)
    if "responseKind" in event:
        if event["responseKind"] is None or event["responseKind"] not in RESPONSE_KINDS:
            raise DecisionStoreError(f"Decision file has an invalid responseKind for {job_id}")

    if "rejectionReason" in event:
        if event["rejectionReason"] is None:
            raise DecisionStoreError(f"Decision file has an invalid rejectionReason for {job_id}")
        _validate_optional_text(event["rejectionReason"], "rejectionReason", 1000)
    if event["status"] != "rejected" and "rejectionReason" in event:
        raise DecisionStoreError(f"Decision file has an invalid rejectionReason for {job_id}")
    return copy.deepcopy(event)


def _current_event(history: list[dict]) -> dict:
    return chronological_history(history)[-1]


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
    if set(store) - _STORE_FIELDS:
        raise DecisionStoreError("Decision file has invalid root fields")
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
    return _read_store(path)[0]


def _read_store(path: Path) -> tuple[dict, int | None, bytes]:
    path = Path(path)
    try:
        source_bytes = path.read_bytes()
    except FileNotFoundError:
        return _empty_store(), None, b""
    except OSError as error:
        raise DecisionStoreError(f"Could not read decision file: {path}") from error
    try:
        store = json.loads(source_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecisionStoreError(f"Decision file is not valid JSON: {path}") from error
    if not isinstance(store, dict) or type(store.get("version")) is not int:
        raise DecisionStoreError("Decision file has an unsupported schema version")
    if store["version"] == 1:
        return _validate_v2(_normalize_v1(store)), 1, source_bytes
    return _validate_v2(store), store["version"], source_bytes


def _open_store_lock(path: Path, lock_path: Path) -> int:
    fd = None
    try:
        try:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            lock_lstat = lock_path.lstat()
            if not stat.S_ISREG(lock_lstat.st_mode):
                raise DecisionStoreError(f"Decision lock is not a regular file: {lock_path}")
            flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(lock_path, flags)

        lock_lstat = lock_path.lstat()
        lock_fstat = os.fstat(fd)
        if not stat.S_ISREG(lock_fstat.st_mode) or not os.path.samestat(
            lock_lstat, lock_fstat
        ):
            raise DecisionStoreError(f"Decision lock changed while opening: {lock_path}")
        if lock_fstat.st_nlink != 1:
            raise DecisionStoreError(f"Decision lock is not independent: {lock_path}")
        try:
            source_stat = path.stat()
        except FileNotFoundError:
            source_stat = None
        if source_stat is not None and os.path.samestat(source_stat, lock_fstat):
            raise DecisionStoreError(f"Decision lock is not independent: {lock_path}")
        return fd
    except DecisionStoreError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    except OSError as error:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        raise DecisionStoreError(f"Could not open decision lock: {lock_path}") from error


@contextmanager
def _store_lock(path: Path):
    path = Path(path)
    lock_path = Path(f"{path}.lock")
    try:
        parent_created = False
        try:
            path.parent.mkdir(mode=0o700, parents=True)
            parent_created = True
        except FileExistsError:
            pass
        if parent_created:
            os.chmod(path.parent, 0o700)
        fd = _open_store_lock(path, lock_path)
    except DecisionStoreError:
        raise
    except OSError as error:
        raise DecisionStoreError(f"Could not open decision lock: {lock_path}") from error

    acquired = False
    state = _StoreLockState()
    primary_error = None
    try:
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, PermissionError) as error:
            raise DecisionStoreError("Decision file is busy; retry the command") from error
        except OSError as error:
            raise DecisionStoreError(f"Could not lock decision file: {lock_path}") from error
        yield state
    except BaseException as error:
        primary_error = error
        raise
    finally:
        close_error = None
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError as error:
            close_error = error
        if close_error is not None and primary_error is None:
            message = f"Could not release decision lock: {lock_path}"
            if state.committed:
                raise DecisionStoreCommittedError(
                    message,
                    state.committed_result,
                ) from close_error
            raise DecisionStoreError(
                message
            ) from close_error


def _read_existing_v1_backup(path: Path, backup_path: Path) -> bytes:
    fd = None
    try:
        backup_lstat = backup_path.lstat()
        if not stat.S_ISREG(backup_lstat.st_mode):
            raise DecisionStoreError(f"Decision backup is not a regular file: {backup_path}")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(backup_path, flags)
        backup_fstat = os.fstat(fd)
        if not stat.S_ISREG(backup_fstat.st_mode) or not os.path.samestat(
            backup_lstat, backup_fstat
        ):
            raise DecisionStoreError(f"Decision backup changed while opening: {backup_path}")
        if backup_fstat.st_nlink != 1:
            raise DecisionStoreError(f"Decision backup is not independent: {backup_path}")
        if os.path.samestat(path.stat(), backup_fstat):
            raise DecisionStoreError(f"Decision backup is not independent: {backup_path}")
        if os.name != "nt" and backup_fstat.st_mode & 0o077:
            raise DecisionStoreError(f"Decision backup is not private: {backup_path}")

        with os.fdopen(fd, "rb") as handle:
            fd = None
            return handle.read()
    except DecisionStoreError:
        raise
    except OSError as error:
        raise DecisionStoreError(f"Could not verify decision backup: {backup_path}") from error
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError as error:
                raise DecisionStoreError(
                    f"Could not verify decision backup: {backup_path}"
                ) from error


def _ensure_v1_backup(path: Path, source_bytes: bytes) -> None:
    backup_path = Path(f"{path}.v1.bak")
    created = False
    fd = None
    try:
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            fd = os.open(backup_path, flags, 0o600)
            created = True
        except FileExistsError:
            if _read_existing_v1_backup(path, backup_path) != source_bytes:
                raise DecisionStoreError(
                    f"Decision backup does not match source: {backup_path}"
                )
            return
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(source_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except DecisionStoreError:
        raise
    except (OSError, UnicodeError) as error:
        cleanup_error = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError as cleanup_failure:
                cleanup_error = cleanup_failure
        if created:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError as cleanup_failure:
                if cleanup_error is None:
                    cleanup_error = cleanup_failure
        if cleanup_error is not None:
            raise DecisionStoreError(
                f"Could not clean up decision backup: {backup_path}"
            ) from cleanup_error
        raise DecisionStoreError(f"Could not create decision backup: {backup_path}") from error


def _atomic_write(path: Path, store: dict) -> None:
    path = Path(path)
    fd = None
    temporary_path = None
    try:
        serialized = json.dumps(store, indent=2, ensure_ascii=False) + "\n"
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError) as error:
        raise DecisionStoreError(f"Could not write decision file: {path}") from error
    finally:
        cleanup_error = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError as error:
                cleanup_error = error
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            raise DecisionStoreError(
                f"Could not clean up decision write: {path}"
            ) from cleanup_error


def validate_event_input(
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


def validate_job_snapshot(job: object) -> None:
    """Validate fields copied from a public detail response into the local store."""
    _snapshot_from_job(job, {})


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
    event = validate_event_input(
        status,
        now,
        event_date,
        note,
        rejection_reason,
        response_kind,
        contact_name,
    )
    result = None
    with _store_lock(path) as lock:
        store, original_version, source_bytes = _read_store(path)
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
        if original_version == 1:
            _ensure_v1_backup(path, source_bytes)
        _atomic_write(path, store)
        result = {"id": job_id, **copy.deepcopy(record)}
        lock.mark_committed(result)
    return result


def get_decision(path: Path, job_id: str) -> dict | None:
    job_id = normalize_job_id(job_id)
    record = load_decisions(path)["jobs"].get(job_id)
    if record is None:
        return None
    return {"id": job_id, **copy.deepcopy(record)}


def chronological_history(history: list[dict]) -> list[dict]:
    """Return events in parsed date/time order, preserving append ties."""
    return [
        copy.deepcopy(event)
        for _, event in sorted(
            enumerate(history),
            key=lambda item: (
                _parse_event_date(item[1]["date"]),
                _parse_utc_timestamp(item[1]["recordedAt"], "recordedAt"),
                item[0],
            ),
        )
    ]


def list_decisions(path: Path, status: str | None = None) -> list[dict]:
    if status is not None and status not in STATUSES:
        raise DecisionStoreError(f"Status must be one of: {', '.join(STATUSES)}")
    selected = [
        {"id": job_id, **copy.deepcopy(record)}
        for job_id, record in load_decisions(path)["jobs"].items()
        if status is None or record["status"] == status
    ]
    return sorted(selected, key=lambda item: item["updatedAt"], reverse=True)


def forget_decision(path: Path, job_id: str) -> bool:
    job_id = normalize_job_id(job_id)
    with _store_lock(path) as lock:
        store, original_version, source_bytes = _read_store(path)
        if job_id not in store["jobs"]:
            return False
        del store["jobs"][job_id]
        if original_version == 1:
            _ensure_v1_backup(path, source_bytes)
        _atomic_write(path, store)
        lock.mark_committed(True)
        return True
