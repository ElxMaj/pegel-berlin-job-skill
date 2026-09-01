import importlib
import json
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
    listed = decisions.list_decisions(state_file, "shortlisted")

    assert normalized["version"] == 2
    assert normalized["jobs"][JOB_ID]["status"] == "shortlisted"
    assert normalized["jobs"][JOB_ID]["history"] == [{
        "status": "shortlisted",
        "date": "2026-09-01",
        "recordedAt": "2026-09-01T08:30:00Z",
    }]
    assert listed[0]["id"] == JOB_ID
    assert state_file.read_bytes() == original_v1_bytes
    assert not Path(f"{state_file}.v1.bak").exists()


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
    shared_parent.chmod(0o755)
    state_file = shared_parent / "job-decisions.json"

    record(decisions, state_file)

    assert stat.S_IMODE(shared_parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
