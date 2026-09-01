import importlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

JOB_ID = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"
SECOND_JOB_ID = "904334d9-9e13-416b-a76d-10acd8790b3e"
JOB = {
    "id": JOB_ID,
    "title": "Founder’s Associate",
    "company": {"slug": "netbird", "name": "NetBird"},
    "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
}


def decisions_module():
    return importlib.import_module("job_decisions")


def record(decisions, path, job_id=JOB_ID, status="shortlisted", **kwargs):
    defaults = {
        "job": None,
        "now": "2026-09-01T08:30:00Z",
        "event_date": "2026-09-01",
    }
    defaults.update(kwargs)
    return decisions.record_decision(path, job_id, status, **defaults)


def v2_record(*, status="shortlisted", date="2026-09-01", recorded_at="2026-09-01T08:30:00Z"):
    return {
        "status": status,
        "updatedAt": "2026-09-01T08:30:00Z",
        "history": [{"status": status, "date": date, "recordedAt": recorded_at}],
    }


def test_record_decision_appends_events_and_derives_current_status(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(
        decisions,
        state_file,
        job=JOB,
        status="shortlisted",
        now="2026-09-01T08:30:00Z",
        event_date="2026-09-01",
    )
    result = record(
        decisions,
        state_file,
        status="applied",
        now="2026-09-02T09:00:00Z",
        event_date="2026-09-02",
        note="Applied on the employer site",
    )

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["jobs"][JOB_ID]["status"] == "applied"
    assert [event["status"] for event in saved["jobs"][JOB_ID]["history"]] == [
        "shortlisted",
        "applied",
    ]
    assert saved["jobs"][JOB_ID]["history"][1]["note"] == "Applied on the employer site"
    assert result == {"id": JOB_ID, **saved["jobs"][JOB_ID]}


def test_record_decision_supports_all_statuses_and_repeated_statuses(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    for index, status in enumerate(decisions.STATUSES):
        record(
            decisions,
            state_file,
            status=status,
            now=f"2026-09-{index + 1:02d}T08:30:00Z",
            event_date=f"2026-09-{index + 1:02d}",
            rejection_reason="Position filled" if status == "rejected" else None,
        )
    record(
        decisions,
        state_file,
        status="passed",
        now="2026-09-10T08:30:00Z",
        event_date="2026-09-10",
    )

    history = decisions.load_decisions(state_file)["jobs"][JOB_ID]["history"]
    assert [event["status"] for event in history] == [*decisions.STATUSES, "passed"]
    assert decisions.load_decisions(state_file)["jobs"][JOB_ID]["status"] == "passed"
    assert decisions.VERDICTS == decisions.STATUSES


def test_record_decision_omits_absent_event_metadata_and_retains_valid_snapshot(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, job=JOB)
    record(decisions, state_file, status="applied", now="2026-09-02T08:30:00Z", event_date="2026-09-02")

    saved = decisions.load_decisions(state_file)["jobs"][JOB_ID]
    assert saved["title"] == "Founder’s Associate"
    assert saved["company"] == "NetBird"
    assert saved["pegelUrl"] == JOB["pegelUrl"]
    assert saved["history"][1] == {
        "status": "applied",
        "date": "2026-09-02",
        "recordedAt": "2026-09-02T08:30:00Z",
    }


def test_record_decision_allows_a_rejected_event_without_a_reason(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, status="rejected")

    assert decisions.get_decision(state_file, JOB_ID)["history"] == [{
        "status": "rejected",
        "date": "2026-09-01",
        "recordedAt": "2026-09-01T08:30:00Z",
    }]


def test_current_status_ignores_an_older_backfilled_event_appended_last(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, status="applied", now="2026-09-03T08:30:00Z", event_date="2026-09-03")
    record(decisions, state_file, status="shortlisted", now="2026-09-04T08:30:00Z", event_date="2026-09-01")

    assert decisions.get_decision(state_file, JOB_ID)["status"] == "applied"


def test_current_status_uses_recorded_at_when_events_share_a_date(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, status="shortlisted", now="2026-09-01T08:30:00Z")
    record(decisions, state_file, status="applied", now="2026-09-01T09:00:00Z")

    assert decisions.get_decision(state_file, JOB_ID)["status"] == "applied"


def test_current_status_uses_append_order_when_event_times_are_identical(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, status="shortlisted")
    record(decisions, state_file, status="applied")

    assert decisions.get_decision(state_file, JOB_ID)["status"] == "applied"


def test_updated_at_is_the_latest_write_not_the_latest_event_date(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, status="applied", now="2026-09-03T08:30:00Z", event_date="2026-09-03")
    record(decisions, state_file, status="shortlisted", now="2026-09-04T08:30:00Z", event_date="2026-09-01")

    saved = decisions.get_decision(state_file, JOB_ID)
    assert saved["status"] == "applied"
    assert saved["updatedAt"] == "2026-09-04T08:30:00Z"


def test_v1_reads_normalize_in_memory_without_writing_or_creating_a_backup(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    original_v1_bytes = json.dumps(
        {
            "version": 1,
            "jobs": {
                JOB_ID: {
                    "verdict": "shortlisted",
                    "updatedAt": "2026-09-01T08:30:00Z",
                    "title": "Founder’s Associate",
                    "company": "NetBird",
                    "pegelUrl": JOB["pegelUrl"],
                }
            },
        },
        indent=2,
    ).encode()
    state_file.write_bytes(original_v1_bytes)

    normalized = decisions.load_decisions(state_file)
    fetched = decisions.get_decision(state_file, JOB_ID)
    listed = decisions.list_decisions(state_file, "shortlisted")

    assert normalized["version"] == 2
    assert normalized["jobs"][JOB_ID]["status"] == "shortlisted"
    assert normalized["jobs"][JOB_ID]["history"] == [{
        "status": "shortlisted",
        "date": "2026-09-01",
        "recordedAt": "2026-09-01T08:30:00Z",
    }]
    assert listed[0]["id"] == JOB_ID
    assert fetched["id"] == JOB_ID
    assert state_file.read_bytes() == original_v1_bytes
    assert not Path(f"{state_file}.v1.bak").exists()


def test_first_v1_mutation_preserves_exact_backup_and_migrates_history(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({
        "version": 1,
        "jobs": {JOB_ID: {
            "verdict": "shortlisted",
            "updatedAt": "2026-08-31T08:00:00Z",
            "title": "Founder’s Associate",
        }},
    }, indent=1, ensure_ascii=False).encode("utf-8")
    state_file.write_bytes(original)

    record(decisions, state_file, status="applied")

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert backup_file.read_bytes() == original
    assert saved["version"] == 2
    assert [event["status"] for event in saved["jobs"][JOB_ID]["history"]] == [
        "shortlisted",
        "applied",
    ]
    if os.name != "nt":
        assert stat.S_IMODE(backup_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


def test_v1_mutation_accepts_an_identical_existing_backup(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    backup_file.write_bytes(original)
    if os.name != "nt":
        backup_file.chmod(0o600)

    record(decisions, state_file)

    assert backup_file.read_bytes() == original
    assert decisions.get_decision(state_file, JOB_ID)["status"] == "shortlisted"


def test_v1_mutation_rejects_a_backup_symlink_to_the_source_without_changes(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    try:
        backup_file.symlink_to(state_file)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert backup_file.is_symlink()


def test_v1_mutation_rejects_a_backup_hard_link_to_the_source_without_changes(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    if os.name != "nt":
        state_file.chmod(0o600)
    try:
        os.link(state_file, backup_file)
    except OSError as error:
        pytest.skip(f"hard links are unavailable: {error}")

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert os.path.samefile(state_file, backup_file)


def test_v1_mutation_rejects_an_existing_backup_with_another_hard_link(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    backup_alias = tmp_path / "backup-alias"
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    backup_file.write_bytes(original)
    if os.name != "nt":
        backup_file.chmod(0o600)
    try:
        os.link(backup_file, backup_alias)
    except OSError as error:
        pytest.skip(f"hard links are unavailable: {error}")

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert backup_file.read_bytes() == original
    assert os.path.samefile(backup_file, backup_alias)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not authoritative on Windows")
def test_v1_mutation_rejects_a_group_or_other_accessible_existing_backup(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    backup_file.write_bytes(original)
    backup_file.chmod(0o644)

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert backup_file.read_bytes() == original
    assert stat.S_IMODE(backup_file.stat().st_mode) == 0o644


def test_v1_mutation_rejects_a_non_regular_existing_backup(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    backup_file.mkdir()

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert backup_file.is_dir()


def test_v1_mutation_rejects_a_different_existing_backup_without_changes(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    conflicting_backup = b"different backup\n"
    state_file.write_bytes(original)
    backup_file.write_bytes(conflicting_backup)
    if os.name != "nt":
        backup_file.chmod(0o600)

    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original
    assert backup_file.read_bytes() == conflicting_backup


def test_mutation_reports_lock_contention_without_changing_source(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    record(decisions, state_file)
    original = state_file.read_bytes()

    with decisions._store_lock(state_file):
        with pytest.raises(
            decisions.DecisionStoreError,
            match="^Decision file is busy; retry the command$",
        ):
            record(decisions, state_file, status="applied")
        with pytest.raises(
            decisions.DecisionStoreError,
            match="^Decision file is busy; retry the command$",
        ):
            decisions.forget_decision(state_file, SECOND_JOB_ID)

    assert state_file.read_bytes() == original


def test_lock_cleanup_attempts_close_when_unlock_and_close_fail(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    original = b"original source\n"
    state_file.write_bytes(original)
    opened = []
    unlock_attempts = []
    close_attempts = []
    real_open = decisions.os.open
    real_close = decisions.os.close

    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def fail_close(fd):
        close_attempts.append(fd)
        raise OSError("close failed")

    with monkeypatch.context() as patch:
        patch.setattr(decisions.os, "open", track_open)
        patch.setattr(decisions.os, "close", fail_close)
        if os.name == "nt":
            import msvcrt

            real_unlock = msvcrt.locking

            def fail_unlock(fd, mode, size):
                if mode == msvcrt.LK_UNLCK:
                    unlock_attempts.append(fd)
                    raise OSError("unlock failed")
                return real_unlock(fd, mode, size)

            patch.setattr(msvcrt, "locking", fail_unlock)
        else:
            import fcntl

            real_unlock = fcntl.flock

            def fail_unlock(fd, operation):
                if operation == fcntl.LOCK_UN:
                    unlock_attempts.append(fd)
                    raise OSError("unlock failed")
                return real_unlock(fd, operation)

            patch.setattr(fcntl, "flock", fail_unlock)

        with pytest.raises(decisions.DecisionStoreError, match="release"):
            with decisions._store_lock(state_file):
                pass

    try:
        assert unlock_attempts == opened
        assert close_attempts == opened
        assert state_file.read_bytes() == original
    finally:
        for fd in opened:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                real_unlock(fd, msvcrt.LK_UNLCK, 1)
            else:
                real_unlock(fd, fcntl.LOCK_UN)
            real_close(fd)


def test_unlock_failure_with_successful_close_does_not_fail_a_committed_record(
    tmp_path, monkeypatch
):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    if os.name == "nt":
        import msvcrt

        real_unlock = msvcrt.locking

        def fail_unlock(fd, mode, size):
            if mode == msvcrt.LK_UNLCK:
                raise OSError("unlock failed")
            return real_unlock(fd, mode, size)

        monkeypatch.setattr(msvcrt, "locking", fail_unlock)
    else:
        import fcntl

        real_unlock = fcntl.flock

        def fail_unlock(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError("unlock failed")
            return real_unlock(fd, operation)

        monkeypatch.setattr(fcntl, "flock", fail_unlock)

    result = record(decisions, state_file)

    assert result["status"] == "shortlisted"
    assert len(decisions.get_decision(state_file, JOB_ID)["history"]) == 1


def test_close_failure_after_commit_exposes_the_committed_result(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    lock_file = Path(f"{state_file}.lock")
    lock_fds = []
    real_open = decisions.os.open
    real_close = decisions.os.close

    def track_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if Path(path) == lock_file:
            lock_fds.append(fd)
        return fd

    def fail_lock_close(fd):
        if fd in lock_fds:
            raise OSError("close failed")
        return real_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(decisions.os, "open", track_open)
            patch.setattr(decisions.os, "close", fail_lock_close)
            with pytest.raises(decisions.DecisionStoreCommittedError) as raised:
                record(decisions, state_file)

        assert raised.value.committed_result["status"] == "shortlisted"
        assert len(decisions.get_decision(state_file, JOB_ID)["history"]) == 1
    finally:
        for fd in lock_fds:
            real_close(fd)


def test_lock_cleanup_does_not_mask_a_primary_body_error(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    lock_file = Path(f"{state_file}.lock")
    lock_fds = []
    real_open = decisions.os.open
    real_close = decisions.os.close

    def track_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if Path(path) == lock_file:
            lock_fds.append(fd)
        return fd

    def fail_lock_close(fd):
        if fd in lock_fds:
            raise OSError("close failed")
        return real_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(decisions.os, "open", track_open)
            patch.setattr(decisions.os, "close", fail_lock_close)
            with pytest.raises(decisions.DecisionStoreError, match="primary body failure"):
                with decisions._store_lock(state_file):
                    raise decisions.DecisionStoreError("primary body failure")
    finally:
        for fd in lock_fds:
            real_close(fd)


def test_parent_creation_race_does_not_chmod_an_existing_directory(tmp_path, monkeypatch):
    decisions = decisions_module()
    parent = tmp_path / "raced"
    state_file = parent / "job-decisions.json"
    real_exists = Path.exists
    real_mkdir = Path.mkdir
    real_chmod = decisions.os.chmod
    parent_chmods = []

    def report_parent_missing(path):
        if path == parent:
            return False
        return real_exists(path)

    def race_mkdir(path, *args, **kwargs):
        if path == parent and not real_exists(parent):
            real_mkdir(parent, mode=0o755, parents=True, exist_ok=True)
            if not kwargs.get("exist_ok", False):
                raise FileExistsError(parent)
            return None
        return real_mkdir(path, *args, **kwargs)

    def track_chmod(path, mode):
        if Path(path) == parent:
            parent_chmods.append(mode)
        return real_chmod(path, mode)

    monkeypatch.setattr(Path, "exists", report_parent_missing)
    monkeypatch.setattr(Path, "mkdir", race_mkdir)
    monkeypatch.setattr(decisions.os, "chmod", track_chmod)

    record(decisions, state_file)

    assert parent_chmods == []
    if os.name != "nt":
        assert stat.S_IMODE(parent.stat().st_mode) == 0o755


def test_backup_creation_failure_keeps_v1_source_intact(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)

    real_open = decisions.os.open

    def fail_backup(path, *args, **kwargs):
        if Path(path) == Path(f"{state_file}.v1.bak"):
            raise OSError("disk unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(decisions.os, "open", fail_backup)
    with pytest.raises(decisions.DecisionStoreError, match="backup"):
        record(decisions, state_file)

    assert state_file.read_bytes() == original


def test_backup_cleanup_attempts_unlink_and_fails_loud(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({"version": 1, "jobs": {}}).encode("utf-8")
    state_file.write_bytes(original)
    opened = []
    close_attempts = []
    unlink_attempts = []
    real_open = decisions.os.open
    real_close = decisions.os.close
    real_unlink = Path.unlink

    def track_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if Path(path) == backup_file:
            opened.append(fd)
        return fd

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    def fail_close(fd):
        close_attempts.append(fd)
        raise OSError("close failed")

    def fail_unlink(path, *args, **kwargs):
        if path == backup_file:
            unlink_attempts.append(path)
            raise OSError("unlink failed")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(decisions.os, "open", track_open)
        patch.setattr(decisions.os, "fdopen", fail_fdopen)
        patch.setattr(decisions.os, "close", fail_close)
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(decisions.DecisionStoreError, match="backup"):
            decisions._ensure_v1_backup(state_file, original)

    try:
        assert close_attempts == opened
        assert unlink_attempts == [backup_file]
        assert state_file.read_bytes() == original
        assert backup_file.exists()
    finally:
        for fd in opened:
            real_close(fd)
        real_unlink(backup_file, missing_ok=True)


def test_atomic_cleanup_attempts_unlink_when_descriptor_close_fails(tmp_path, monkeypatch):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    original = b"original source\n"
    state_file.write_bytes(original)
    opened = []
    temporary_paths = []
    close_attempts = []
    unlink_attempts = []
    real_mkstemp = decisions.tempfile.mkstemp
    real_close = decisions.os.close
    real_unlink = Path.unlink

    def track_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        opened.append(fd)
        temporary_paths.append(Path(name))
        return fd, name

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    def fail_close(fd):
        close_attempts.append(fd)
        raise OSError("close failed")

    def track_unlink(path, *args, **kwargs):
        if path in temporary_paths:
            unlink_attempts.append(path)
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(decisions.tempfile, "mkstemp", track_mkstemp)
        patch.setattr(decisions.os, "fdopen", fail_fdopen)
        patch.setattr(decisions.os, "close", fail_close)
        patch.setattr(Path, "unlink", track_unlink)
        with pytest.raises(decisions.DecisionStoreError, match="write"):
            decisions._atomic_write(state_file, {"version": 2, "jobs": {}})

    try:
        assert close_attempts == opened
        assert unlink_attempts == temporary_paths
        assert state_file.read_bytes() == original
    finally:
        for fd in opened:
            real_close(fd)
        for path in temporary_paths:
            real_unlink(path, missing_ok=True)


@pytest.mark.parametrize(
    "boundary", ["serialization", "temporary write", "chmod", "replace"]
)
def test_atomic_write_failures_keep_source_intact(tmp_path, monkeypatch, boundary):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    record(decisions, state_file)
    original = state_file.read_bytes()

    def fail(*_args, **_kwargs):
        if boundary == "serialization":
            raise TypeError("not serializable")
        raise OSError(f"failed {boundary}")

    if boundary == "serialization":
        monkeypatch.setattr(decisions.json, "dumps", fail)
    elif boundary == "temporary write":
        monkeypatch.setattr(decisions.tempfile, "mkstemp", fail)
    elif boundary == "chmod":
        monkeypatch.setattr(decisions.os, "chmod", fail)
    else:
        monkeypatch.setattr(decisions.os, "replace", fail)

    with pytest.raises(decisions.DecisionStoreError, match="write"):
        record(decisions, state_file, status="applied")

    assert state_file.read_bytes() == original


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 3, "jobs": {}}, "unsupported schema version"),
        ({"version": True, "jobs": {}}, "unsupported schema version"),
        ({"version": 2.0, "jobs": {}}, "unsupported schema version"),
        ({"version": 2, "jobs": []}, "jobs must be an object"),
        ({"version": 2, "jobs": {"not-a-uuid": v2_record()}}, "full Pegel job UUID"),
        ({"version": 2, "jobs": {JOB_ID: []}}, "invalid record"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "history": []}}}, "invalid history"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "status": "unknown"}}}, "invalid status"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "updatedAt": "2026-09-01T08:30:00+00:00"}}}, "invalid updatedAt"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(date="2026-02-30")}}}, "invalid date"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(recorded_at="2026-09-01T08:30:00+00:00")}}}, "invalid recordedAt"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "title": ["Role"]}}}, "invalid title"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "company": "Company\x1b"}}}, "invalid company"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "pegelUrl": "https://evil.example/role"}}}, "invalid pegelUrl"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "history": [{**v2_record()["history"][0], "note": None}]}}}, "invalid note"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(status="rejected"), "history": [{**v2_record(status="rejected")["history"][0], "rejectionReason": None}]}}}, "invalid rejectionReason"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "history": [{**v2_record()["history"][0], "responseKind": None}]}}}, "invalid responseKind"),
        ({"version": 2, "jobs": {JOB_ID: {**v2_record(), "history": [{**v2_record()["history"][0], "contactName": None}]}}}, "invalid contactName"),
    ],
)
def test_load_decisions_rejects_malformed_v2_state_without_rewriting_it(tmp_path, payload, message):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    original = json.dumps(payload).encode()
    state_file.write_bytes(original)

    with pytest.raises(decisions.DecisionStoreError, match=message):
        decisions.load_decisions(state_file)

    assert state_file.read_bytes() == original


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "unknown"}, "Status must be one of"),
        ({"event_date": "2026-2-01"}, "invalid date"),
        ({"event_date": "2026-02-30"}, "invalid date"),
        ({"now": "2026-09-01T08:30:00+00:00"}, "recordedAt"),
        ({"now": "2026-09-01T08:30:00Z", "rejection_reason": "No", "status": "applied"}, "rejectionReason"),
        ({"status": "rejected", "rejection_reason": "x" * 1001}, "rejectionReason"),
        ({"note": "x" * 4001}, "note"),
        ({"contact_name": "x" * 201}, "contactName"),
        ({"note": "unsafe\x00"}, "note"),
        ({"response_kind": "bot"}, "responseKind"),
        ({"job": {"title": ["Role"]}}, "title"),
        ({"job": {"company": {"name": "Company\x1b"}}}, "company"),
        ({"job": {"pegelUrl": "https://evil.example/role"}}, "pegelUrl"),
    ],
)
def test_record_decision_rejects_invalid_event_input_without_changing_state(tmp_path, kwargs, message):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    record(decisions, state_file)
    original = state_file.read_bytes()

    with pytest.raises(decisions.DecisionStoreError, match=message):
        record(decisions, state_file, **kwargs)

    assert state_file.read_bytes() == original


def test_record_decision_persists_event_metadata_and_private_file_permissions(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "pegel" / "job-decisions.json"

    record(
        decisions,
        state_file,
        status="rejected",
        job=JOB,
        note="Follow up next quarter",
        rejection_reason="Position filled",
        response_kind="human",
        contact_name="Camille Martin",
    )

    event = decisions.load_decisions(state_file)["jobs"][JOB_ID]["history"][0]
    assert event == {
        "status": "rejected",
        "date": "2026-09-01",
        "recordedAt": "2026-09-01T08:30:00Z",
        "note": "Follow up next quarter",
        "rejectionReason": "Position filled",
        "responseKind": "human",
        "contactName": "Camille Martin",
    }
    if os.name != "nt":
        assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(state_file.parent.stat().st_mode) == 0o700


def test_list_decisions_filters_by_status_and_orders_latest_writes_first(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    record(decisions, state_file, JOB_ID, "shortlisted", now="2026-09-01T08:00:00Z")
    record(decisions, state_file, SECOND_JOB_ID, "passed", now="2026-09-01T09:00:00Z")
    record(decisions, state_file, JOB_ID, "applied", now="2026-09-01T10:00:00Z")

    applied = decisions.list_decisions(state_file, "applied")
    all_items = decisions.list_decisions(state_file)

    assert [item["id"] for item in applied] == [JOB_ID]
    assert [item["id"] for item in all_items] == [JOB_ID, SECOND_JOB_ID]


def test_forget_decision_returns_the_job_to_future_searches(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    record(decisions, state_file, status="passed")

    assert decisions.forget_decision(state_file, JOB_ID) is True
    assert decisions.load_decisions(state_file)["jobs"] == {}
    assert decisions.forget_decision(state_file, JOB_ID) is False


def test_forget_removes_only_the_active_log_and_retains_an_exact_v1_backup(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    backup_file = Path(f"{state_file}.v1.bak")
    original = json.dumps({
        "version": 1,
        "jobs": {JOB_ID: {"verdict": "passed", "updatedAt": "2026-09-01T08:30:00Z"}},
    }).encode("utf-8")
    state_file.write_bytes(original)

    assert decisions.forget_decision(state_file, JOB_ID) is True

    assert decisions.load_decisions(state_file)["jobs"] == {}
    assert backup_file.read_bytes() == original


def test_decision_path_supports_an_explicit_override_and_xdg_storage(tmp_path, monkeypatch):
    decisions = decisions_module()
    explicit = tmp_path / "explicit.json"
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("PEGEL_DECISIONS_FILE", str(explicit))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    assert decisions.decision_path() == explicit
    assert decisions.decision_path(tmp_path / "cli.json") == tmp_path / "cli.json"

    monkeypatch.delenv("PEGEL_DECISIONS_FILE")
    assert decisions.decision_path() == xdg / "pegel" / "job-decisions.json"


def test_custom_state_file_does_not_change_permissions_on_an_existing_parent(tmp_path):
    decisions = decisions_module()
    shared_parent = tmp_path / "shared"
    shared_parent.mkdir(mode=0o755)
    if os.name != "nt":
        shared_parent.chmod(0o755)
    state_file = shared_parent / "job-decisions.json"

    record(decisions, state_file)

    if os.name != "nt":
        assert stat.S_IMODE(shared_parent.stat().st_mode) == 0o755
        assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
