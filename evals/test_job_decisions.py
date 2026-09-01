import importlib
import json
import stat
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def decisions_module():
    return importlib.import_module("job_decisions")


def test_record_decision_persists_a_private_versioned_job_snapshot(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "pegel" / "job-decisions.json"
    job = {
        "id": "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
        "title": "Founder’s Associate",
        "company": {"slug": "netbird", "name": "NetBird"},
        "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
    }

    decisions.record_decision(
        state_file,
        job["id"],
        "shortlisted",
        job=job,
        now="2026-09-01T08:30:00Z",
    )

    assert json.loads(state_file.read_text()) == {
        "version": 1,
        "jobs": {
            job["id"]: {
                "verdict": "shortlisted",
                "updatedAt": "2026-09-01T08:30:00Z",
                "title": "Founder’s Associate",
                "company": "NetBird",
                "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
            }
        },
    }
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_file.parent.stat().st_mode) == 0o700


def test_revising_a_verdict_keeps_the_existing_snapshot_when_lookup_is_unavailable(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    job_id = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"
    job = {
        "title": "Founder’s Associate",
        "company": {"name": "NetBird"},
        "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
    }
    decisions.record_decision(
        state_file,
        job_id,
        "shortlisted",
        job=job,
        now="2026-09-01T08:30:00Z",
    )

    decisions.record_decision(
        state_file,
        job_id,
        "applied",
        job=None,
        now="2026-09-02T09:00:00Z",
    )

    saved = json.loads(state_file.read_text())["jobs"][job_id]
    assert saved == {
        "verdict": "applied",
        "updatedAt": "2026-09-02T09:00:00Z",
        "title": "Founder’s Associate",
        "company": "NetBird",
        "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
    }


def test_record_decision_rejects_an_unknown_verdict_without_creating_state(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    with pytest.raises(decisions.DecisionStoreError, match="shortlisted, applied, passed"):
        decisions.record_decision(
            state_file,
            "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
            "rejected",
            job=None,
            now="2026-09-01T08:30:00Z",
        )

    assert not state_file.exists()


def test_record_decision_rejects_a_non_uuid_job_key(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"

    with pytest.raises(decisions.DecisionStoreError, match="full Pegel job UUID"):
        decisions.record_decision(
            state_file,
            "f623bce6",
            "shortlisted",
            job=None,
            now="2026-09-01T08:30:00Z",
        )

    assert not state_file.exists()


def test_load_decisions_fails_loud_without_replacing_corrupt_json(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    corrupt = b'{"version": 1, "jobs": '
    state_file.write_bytes(corrupt)

    with pytest.raises(decisions.DecisionStoreError, match="not valid JSON"):
        decisions.load_decisions(state_file)

    assert state_file.read_bytes() == corrupt


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 2, "jobs": {}}, "unsupported schema version"),
        ({"version": True, "jobs": {}}, "unsupported schema version"),
        ({"version": 1.0, "jobs": {}}, "unsupported schema version"),
        ({"version": 1, "jobs": []}, "jobs must be an object"),
        (
            {
                "version": 1,
                "jobs": {
                    "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c": {
                        "verdict": "rejected",
                        "updatedAt": "2026-09-01T08:30:00Z",
                    }
                },
            },
            "invalid verdict",
        ),
    ],
)
def test_load_decisions_rejects_an_unknown_or_malformed_schema(tmp_path, payload, message):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    state_file.write_text(json.dumps(payload))

    with pytest.raises(decisions.DecisionStoreError, match=message):
        decisions.load_decisions(state_file)


def test_list_decisions_filters_by_verdict_and_orders_newest_first(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    ids = [
        "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
        "904334d9-9e13-416b-a76d-10acd8790b3e",
        "e0b06dbd-2d33-465e-858c-c54d724c4309",
    ]
    decisions.record_decision(state_file, ids[0], "shortlisted", job=None, now="2026-09-01T08:00:00Z")
    decisions.record_decision(state_file, ids[1], "passed", job=None, now="2026-09-01T09:00:00Z")
    decisions.record_decision(state_file, ids[2], "shortlisted", job=None, now="2026-09-01T10:00:00Z")

    shortlisted = decisions.list_decisions(state_file, "shortlisted")

    assert [item["id"] for item in shortlisted] == [ids[2], ids[0]]
    assert all(item["verdict"] == "shortlisted" for item in shortlisted)


def test_forget_decision_returns_the_job_to_future_searches(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    job_id = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"
    decisions.record_decision(
        state_file,
        job_id,
        "passed",
        job=None,
        now="2026-09-01T08:30:00Z",
    )

    assert decisions.forget_decision(state_file, job_id) is True
    assert decisions.load_decisions(state_file)["jobs"] == {}
    assert decisions.forget_decision(state_file, job_id) is False


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


@pytest.mark.parametrize(
    "pegel_url",
    [
        "https://evil.example/apply",
        "https://pegel.berlin/jobs/role\nhttps://evil.example/apply",
        "https://pegel.berlin/jobs/role\x1b]52;c;tampered\x07",
        "https://user@pegel.berlin/jobs/role",
    ],
)
def test_record_decision_never_saves_an_untrusted_url_under_a_pegel_label(
    tmp_path,
    pegel_url,
):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    job_id = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"

    decisions.record_decision(
        state_file,
        job_id,
        "shortlisted",
        job={"title": "Role", "company": {"name": "Company"}, "pegelUrl": pegel_url},
        now="2026-09-01T08:30:00Z",
    )

    assert decisions.load_decisions(state_file)["jobs"][job_id]["pegelUrl"] is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("updatedAt", None, "invalid updatedAt"),
        ("title", 42, "invalid title"),
        ("company", ["Example"], "invalid company"),
        ("pegelUrl", "https://evil.example/role", "invalid pegelUrl"),
        (
            "pegelUrl",
            "https://pegel.berlin/jobs/role\x1b]52;c;tampered\x07",
            "invalid pegelUrl",
        ),
    ],
)
def test_load_decisions_rejects_malformed_snapshot_fields(tmp_path, field, value, message):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    job_id = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"
    item = {
        "verdict": "shortlisted",
        "updatedAt": "2026-09-01T08:30:00Z",
        "title": "Role",
        "company": "Example GmbH",
        "pegelUrl": "https://pegel.berlin/jobs/role-f623bce6",
    }
    item[field] = value
    state_file.write_text(json.dumps({"version": 1, "jobs": {job_id: item}}))

    with pytest.raises(decisions.DecisionStoreError, match=message):
        decisions.load_decisions(state_file)


def test_record_decision_discards_malformed_optional_snapshot_text(tmp_path):
    decisions = decisions_module()
    state_file = tmp_path / "job-decisions.json"
    job_id = "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c"

    decisions.record_decision(
        state_file,
        job_id,
        "shortlisted",
        job={"title": ["Role"], "company": {"name": 42}, "pegelUrl": None},
        now="2026-09-01T08:30:00Z",
    )

    saved = decisions.load_decisions(state_file)["jobs"][job_id]
    assert saved["title"] is None
    assert saved["company"] is None


def test_custom_state_file_does_not_change_permissions_on_an_existing_parent(tmp_path):
    decisions = decisions_module()
    shared_parent = tmp_path / "shared"
    shared_parent.mkdir(mode=0o755)
    shared_parent.chmod(0o755)
    state_file = shared_parent / "job-decisions.json"

    decisions.record_decision(
        state_file,
        "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
        "shortlisted",
        job=None,
        now="2026-09-01T08:30:00Z",
    )

    assert stat.S_IMODE(shared_parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
