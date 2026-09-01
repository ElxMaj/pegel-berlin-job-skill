import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pegel_query  # noqa: E402
import job_decisions  # noqa: E402
from job_decisions import record_decision  # noqa: E402


IDS = [
    "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
    "904334d9-9e13-416b-a76d-10acd8790b3e",
    "e0b06dbd-2d33-465e-858c-c54d724c4309",
    "994c5517-70c0-4bbd-b142-f66f21f3f28d",
]


def api_job(job_id, title):
    return {
        "id": job_id,
        "slug": f"{title.lower().replace(' ', '-')}-{job_id[:8]}",
        "title": title,
        "company": {"slug": "example", "name": "Example GmbH"},
        "location": "Berlin",
        "seniorityRaw": "senior",
        "contractTypeRaw": "full_time",
        "languageTier": "none",
        "visaTier": None,
        "remoteModeTier": "hybrid",
        "salaryMin": None,
        "salaryMax": None,
        "salaryCurrency": None,
        "salaryPeriod": None,
        "techTags": ["python"],
        "summaryText": None,
        "postedAt": "2026-08-31T12:00:00Z",
        "firstSeenAt": "2026-08-31T13:00:00Z",
        "lastSeenAt": "2026-09-01T04:00:00Z",
        "status": "active",
        "expiredAt": None,
        "atsUrl": "https://jobs.example.test/role",
        "pegelUrl": f"https://pegel.berlin/jobs/{title.lower().replace(' ', '-')}-{job_id[:8]}",
    }


def test_collect_jobs_filters_decisions_and_keeps_paging_until_the_limit():
    pages = {
        1: [api_job(IDS[0], "Passed role"), api_job(IDS[1], "Fresh one")],
        2: [api_job(IDS[2], "Applied role"), api_job(IDS[3], "Fresh two")],
    }
    calls = []

    def fetch_page(params):
        calls.append(dict(params))
        page = int(params["page"])
        return {
            "data": pages[page],
            "pagination": {"page": page, "pageSize": 100, "totalCount": 4, "totalPages": 2},
        }

    result = pegel_query.collect_jobs(
        {"q": "engineer"},
        limit=2,
        decided_ids={IDS[0], IDS[2]},
        fetch_page=fetch_page,
    )

    assert [job["id"] for job in result.jobs] == [IDS[1], IDS[3]]
    assert result.api_total_count == 4
    assert result.scanned == 4
    assert result.decided_excluded == 2
    assert result.pages_fetched == 2
    assert calls == [
        {"q": "engineer", "page": "1", "pageSize": "100"},
        {"q": "engineer", "page": "2", "pageSize": "100"},
    ]


def test_collect_jobs_can_include_decided_roles_for_an_explicit_review():
    calls = []

    def fetch_page(params):
        calls.append(dict(params))
        return {
            "data": [api_job(IDS[0], "Passed role"), api_job(IDS[1], "Fresh role")],
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 2, "totalPages": 1},
        }

    result = pegel_query.collect_jobs(
        {},
        limit=2,
        decided_ids={IDS[0]},
        include_decided=True,
        fetch_page=fetch_page,
    )

    assert [job["id"] for job in result.jobs] == [IDS[0], IDS[1]]
    assert result.decided_excluded == 0
    assert calls == [{"page": "1", "pageSize": "100"}]


def test_mark_command_saves_the_status_locally_without_sending_it_to_the_api(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    api_reads = []
    stdout = StringIO()

    def fetch_detail(job_id):
        api_reads.append(job_id)
        return api_job(job_id, "Founder Associate")

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark", IDS[0], "shortlisted"],
        fetch_detail=fetch_detail,
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=stdout,
    )

    assert exit_code == 0
    assert api_reads == [IDS[0]]
    assert "shortlisted" in stdout.getvalue()
    assert '"status": "shortlisted"' in state_file.read_text()


def test_mark_command_uses_a_normal_read_to_keep_a_local_job_snapshot(tmp_path, monkeypatch):
    state_file = tmp_path / "job-decisions.json"
    api_reads = []

    def fetch_job(job_id):
        api_reads.append(job_id)
        return api_job(job_id, "Saved role")

    monkeypatch.setattr(pegel_query, "fetch_job", fetch_job, raising=False)
    pegel_query.main(
        ["--state-file", str(state_file), "--mark", IDS[0], "shortlisted"],
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=StringIO(),
    )

    saved = state_file.read_text()
    assert api_reads == [IDS[0]]
    assert '"title": "Saved role"' in saved
    assert '"pegelUrl": "https://pegel.berlin/jobs/saved-role-f623bce6"' in saved


def test_list_decisions_reads_a_shortlist_offline(tmp_path, monkeypatch):
    state_file = tmp_path / "job-decisions.json"
    job = api_job(IDS[0], "Saved role")
    record_decision(
        state_file,
        IDS[0],
        "shortlisted",
        job=job,
        now="2026-09-01T08:30:00Z",
    )
    stdout = StringIO()

    def unexpected_api_call(*_args, **_kwargs):
        raise AssertionError("listing local decisions must not call Pegel")

    monkeypatch.setattr(pegel_query, "fetch", unexpected_api_call)
    monkeypatch.setattr(pegel_query, "fetch_job", unexpected_api_call)
    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--list-decisions", "shortlisted"],
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "1 shortlisted role" in output
    assert "Saved role" in output
    assert "Example GmbH" in output
    assert IDS[0] in output
    assert job["pegelUrl"] in output


def test_forget_command_makes_a_role_unjudged_again(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    record_decision(
        state_file,
        IDS[0],
        "passed",
        job=api_job(IDS[0], "Passed role"),
        now="2026-09-01T08:30:00Z",
    )
    stdout = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--forget", IDS[0]],
        stdout=stdout,
    )

    assert exit_code == 0
    assert "will appear in normal searches again" in stdout.getvalue()
    assert '"jobs": {}' in state_file.read_text()


def test_search_command_filters_decisions_in_json_and_pages_for_unseen_roles(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    for job_id, verdict in ((IDS[0], "passed"), (IDS[2], "applied")):
        record_decision(
            state_file,
            job_id,
            verdict,
            job=None,
            now="2026-09-01T08:30:00Z",
        )
    pages = {
        1: [api_job(IDS[0], "Passed role"), api_job(IDS[1], "Fresh one")],
        2: [api_job(IDS[2], "Applied role"), api_job(IDS[3], "Fresh two")],
    }

    def fetch_page(params):
        page = int(params["page"])
        return {
            "data": pages[page],
            "pagination": {"page": page, "pageSize": 100, "totalCount": 4, "totalPages": 2},
        }

    stdout = StringIO()
    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--q", "engineer", "--limit", "2", "--json"],
        fetch_page=fetch_page,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert [job["id"] for job in payload["data"]] == [IDS[1], IDS[3]]
    assert payload["pagination"] == {
        "page": 1,
        "pageSize": 2,
        "totalCount": 4,
        "totalPages": 2,
    }
    assert payload["selection"] == {
        "returned": 2,
        "apiMatches": 4,
        "scanned": 4,
        "decidedExcluded": 2,
        "decidedFiltering": True,
    }


def test_mark_command_keeps_the_local_decision_when_snapshot_read_fails(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    stdout = StringIO()
    stderr = StringIO()

    def offline(_job_id):
        raise pegel_query.PegelApiError("Could not reach Pegel")

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark", IDS[0], "passed", "--json"],
        fetch_detail=offline,
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue())["data"]["status"] == "passed"
    assert "saved without a job snapshot" in stderr.getvalue()
    saved = json.loads(state_file.read_text())["jobs"][IDS[0]]
    assert saved["status"] == "passed"
    assert "title" not in saved


@pytest.mark.parametrize(
    "malformed_snapshot",
    [
        {"title": ["Not text"]},
        {"company": "Not an object"},
        {"company": {"slug": "example", "name": ["Not text"]}},
        {"pegelUrl": "https://evil.example/jobs/role"},
    ],
)
def test_malformed_public_snapshot_saves_private_mark_without_snapshot_or_metadata_request(
    tmp_path, monkeypatch, malformed_snapshot
):
    state_file = tmp_path / "job-decisions.json"
    calls = []
    stderr = StringIO()
    private_payload = {
        "jobId": IDS[0],
        "status": "rejected",
        "note": "Private follow up",
        "rejectionReason": "Private reason",
        "responseKind": "human",
        "contactName": "Private contact",
    }
    malformed_job = api_job(IDS[0], "Saved role")
    malformed_job.update(malformed_snapshot)

    def fetch_json(url, **kwargs):
        calls.append((url, kwargs))
        return {"data": malformed_job}

    monkeypatch.setattr(pegel_query, "_fetch_json", fetch_json)

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark-json-stdin"],
        stdin=StringIO(json.dumps(private_payload)),
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 0
    saved = json.loads(state_file.read_text())["jobs"][IDS[0]]
    assert calls == [(f"{pegel_query.API}/{IDS[0]}", {"allow_not_found": True})]
    assert "Private" not in repr(calls)
    assert "saved without a job snapshot" in stderr.getvalue()
    assert saved["history"][0]["note"] == "Private follow up"
    assert saved["history"][0]["rejectionReason"] == "Private reason"
    assert saved["history"][0]["contactName"] == "Private contact"
    assert not {"title", "company", "pegelUrl"} & set(saved)


@pytest.mark.parametrize("read_result", [b"\xff", OSError("response body read failed")])
def test_mark_command_keeps_the_decision_when_the_http_body_cannot_be_read(
    tmp_path,
    monkeypatch,
    read_result,
):
    state_file = tmp_path / "job-decisions.json"
    stderr = StringIO()

    class UnreadableResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            if isinstance(read_result, Exception):
                raise read_result
            return read_result

    monkeypatch.setattr(
        pegel_query.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: UnreadableResponse(),
    )

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark", IDS[0], "shortlisted"],
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 0
    assert "saved without a job snapshot" in stderr.getvalue()
    assert json.loads(state_file.read_text())["jobs"][IDS[0]]["status"] == "shortlisted"


def test_unknown_status_is_rejected_before_any_api_read(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    api_reads = []
    stderr = StringIO()

    def fetch_detail(job_id):
        api_reads.append(job_id)
        return api_job(job_id, "Role")

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark", IDS[0], "unknown"],
        fetch_detail=fetch_detail,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert api_reads == []
    assert "shortlisted, applied, interviewing, offered, accepted, rejected, withdrawn, passed" in stderr.getvalue()
    assert not state_file.exists()


def test_short_job_suffix_is_rejected_before_any_api_read(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    api_reads = []
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark", "f623bce6", "shortlisted"],
        fetch_detail=lambda job_id: api_reads.append(job_id),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert api_reads == []
    assert "full Pegel job UUID" in stderr.getvalue()
    assert not state_file.exists()


def test_collect_jobs_rejects_a_malformed_api_page_instead_of_treating_it_as_empty():
    def malformed_page(_params):
        return {
            "data": "not-a-job-array",
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 1, "totalPages": 1},
        }

    with pytest.raises(pegel_query.PegelApiError, match="invalid job-list response"):
        pegel_query.collect_jobs(
            {},
            limit=1,
            decided_ids=set(),
            fetch_page=malformed_page,
        )


def test_list_command_reports_corrupt_local_state_without_a_traceback(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    state_file.write_text("not json")
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--list-decisions", "all"],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 1
    assert "not valid JSON" in stderr.getvalue()


def test_collect_jobs_deduplicates_a_role_that_moves_between_live_pages():
    pages = {
        1: [api_job(IDS[0], "Fresh one")],
        2: [api_job(IDS[0], "Fresh one")],
        3: [api_job(IDS[1], "Fresh two")],
    }

    def fetch_page(params):
        page = int(params["page"])
        return {
            "data": pages[page],
            "pagination": {"page": page, "pageSize": 100, "totalCount": 2, "totalPages": 3},
        }

    result = pegel_query.collect_jobs(
        {},
        limit=2,
        decided_ids=set(),
        fetch_page=fetch_page,
    )

    assert [job["id"] for job in result.jobs] == [IDS[0], IDS[1]]
    assert result.pages_fetched == 3


def test_decision_commands_are_mutually_exclusive(tmp_path):
    state_file = tmp_path / "job-decisions.json"

    with pytest.raises(SystemExit) as raised:
        pegel_query.main(
            [
                "--state-file",
                str(state_file),
                "--mark",
                IDS[0],
                "shortlisted",
                "--forget",
                IDS[0],
            ],
            fetch_detail=lambda job_id: api_job(job_id, "Role"),
            stdout=StringIO(),
        )

    assert raised.value.code == 2
    assert not state_file.exists()


def test_collect_jobs_rejects_a_role_without_a_full_job_uuid():
    malformed_job = api_job(IDS[0], "Role")
    malformed_job["id"] = "f623bce6"

    def fetch_page(_params):
        return {
            "data": [malformed_job],
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 1, "totalPages": 1},
        }

    with pytest.raises(pegel_query.PegelApiError, match="invalid job ID"):
        pegel_query.collect_jobs(
            {},
            limit=1,
            decided_ids=set(),
            fetch_page=fetch_page,
        )


def test_text_search_prints_the_full_id_needed_for_a_later_decision(tmp_path):
    def fetch_page(_params):
        return {
            "data": [api_job(IDS[0], "Fresh role")],
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 1, "totalPages": 1},
        }

    stdout = StringIO()
    exit_code = pegel_query.main(
        ["--state-file", str(tmp_path / "decisions.json"), "--limit", "1"],
        fetch_page=fetch_page,
        stdout=stdout,
    )

    assert exit_code == 0
    assert f"Job ID     : {IDS[0]}" in stdout.getvalue()


def test_text_search_never_prints_a_control_character_url_under_the_pegel_label(tmp_path):
    hostile_job = api_job(IDS[0], "Fresh role")
    hostile_job["pegelUrl"] = "https://pegel.berlin/jobs/role\x1b]52;c;tampered\x07"

    def fetch_page(_params):
        return {
            "data": [hostile_job],
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 1, "totalPages": 1},
        }

    stdout = StringIO()
    exit_code = pegel_query.main(
        ["--state-file", str(tmp_path / "decisions.json"), "--limit", "1"],
        fetch_page=fetch_page,
        stdout=stdout,
    )

    assert exit_code == 0
    assert "\x1b" not in stdout.getvalue()
    assert "Read/apply : unknown (no Pegel link in this record)" in stdout.getvalue()


def test_include_decided_flag_is_wired_through_the_search_command(tmp_path):
    state_file = tmp_path / "decisions.json"
    record_decision(
        state_file,
        IDS[0],
        "passed",
        job=None,
        now="2026-09-01T08:30:00Z",
    )

    def fetch_page(_params):
        return {
            "data": [api_job(IDS[0], "Passed role")],
            "pagination": {"page": 1, "pageSize": 100, "totalCount": 1, "totalPages": 1},
        }

    stdout = StringIO()
    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--include-decided", "--limit", "1", "--json"],
        fetch_page=fetch_page,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert [job["id"] for job in payload["data"]] == [IDS[0]]
    assert payload["selection"]["decidedFiltering"] is False


@pytest.mark.parametrize(
    "status",
    [
        "shortlisted",
        "applied",
        "interviewing",
        "offered",
        "accepted",
        "rejected",
        "withdrawn",
        "passed",
    ],
)
def test_mark_command_supports_the_complete_status_vocabulary(tmp_path, status):
    stdout = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(tmp_path / f"{status}.json"), "--mark", IDS[0], status],
        fetch_detail=lambda _job_id: None,
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=stdout,
    )

    assert exit_code == 0
    assert status in stdout.getvalue()
    if status == "passed":
        assert "you chose not to pursue this role" in stdout.getvalue().lower()
        assert "interview" not in stdout.getvalue().lower()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--date", "2026-09-01"],
        ["--note", "Follow up"],
        ["--reason", "Position filled"],
        ["--response-kind", "human"],
        ["--contact-name", "Alex"],
        ["--mark", IDS[0], "applied", "--reason", "Position filled"],
        ["--mark", IDS[0], "applied", "--date", "2026-02-30"],
        ["--mark", IDS[0], "applied", "--response-kind", "bot"],
        ["--mark", IDS[0], "applied", "--note", "x" * 4001],
        ["--mark", IDS[0], "rejected", "--reason", "x" * 1001],
        ["--mark", IDS[0], "applied", "--contact-name", "x" * 201],
        ["--mark", IDS[0], "applied", "--note", "unsafe\x00"],
        ["--mark", "f623bce6", "applied"],
        ["--mark", IDS[0], "unknown"],
    ],
)
def test_invalid_local_arguments_are_rejected_before_network_or_write(tmp_path, arguments):
    state_file = tmp_path / "job-decisions.json"
    original = b'{"version": 2, "jobs": {}}\n'
    state_file.write_bytes(original)
    stderr = StringIO()

    def unexpected_detail(_job_id):
        raise AssertionError("invalid input must not call Pegel")

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), *arguments],
        fetch_detail=unexpected_detail,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "Decision error:" in stderr.getvalue()
    assert state_file.read_bytes() == original


def test_mark_json_has_one_data_envelope_and_keeps_metadata_out_of_the_request(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    requested = []
    stdout = StringIO()
    now_calls = []

    def fetch_detail(job_id):
        requested.append(job_id)
        return api_job(job_id, "Saved role")

    def now():
        now_calls.append(True)
        return "2026-09-01T08:30:00Z"

    exit_code = pegel_query.main(
        [
            "--state-file", str(state_file),
            "--mark", IDS[0].upper(), "rejected",
            "--date", "2026-08-31",
            "--note", "Follow up next quarter",
            "--reason", "Position filled",
            "--response-kind", "human",
            "--contact-name", "Alex Martin",
            "--json",
        ],
        fetch_detail=fetch_detail,
        now=now,
        stdout=stdout,
    )

    complete_record = {
        "id": IDS[0],
        "status": "rejected",
        "updatedAt": "2026-09-01T08:30:00Z",
        "history": [{
            "status": "rejected",
            "date": "2026-08-31",
            "recordedAt": "2026-09-01T08:30:00Z",
            "note": "Follow up next quarter",
            "rejectionReason": "Position filled",
            "responseKind": "human",
            "contactName": "Alex Martin",
        }],
        "title": "Saved role",
        "company": "Example GmbH",
        "pegelUrl": f"https://pegel.berlin/jobs/saved-role-{IDS[0][:8]}",
    }
    assert exit_code == 0
    assert requested == [IDS[0]]
    assert len(now_calls) == 1
    assert json.loads(stdout.getvalue()) == {"data": complete_record}


def test_mark_json_stdin_keeps_the_complete_private_mark_out_of_child_argv(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    requested = []
    stdout = StringIO()
    payload = {
        "jobId": IDS[0].upper(),
        "status": "rejected",
        "date": "2026-08-31",
        "note": "Follow up next quarter",
        "rejectionReason": "Position filled",
        "responseKind": "human",
        "contactName": "Alex Martin",
    }

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark-json-stdin", "--json"],
        stdin=StringIO(json.dumps(payload)),
        fetch_detail=lambda job_id: requested.append(job_id) or api_job(job_id, "Saved role"),
        now=lambda: "2026-09-01T08:30:00Z",
        stdout=stdout,
    )

    saved = json.loads(stdout.getvalue())["data"]
    assert exit_code == 0
    assert requested == [IDS[0]]
    assert saved["history"] == [{
        "status": "rejected",
        "date": "2026-08-31",
        "recordedAt": "2026-09-01T08:30:00Z",
        "note": "Follow up next quarter",
        "rejectionReason": "Position filled",
        "responseKind": "human",
        "contactName": "Alex Martin",
    }]


@pytest.mark.parametrize(
    ("raw_payload", "message"),
    [
        (json.dumps({"jobId": IDS[0], "status": "shortlisted", "extra": True}), "unknown"),
        (json.dumps({"status": "shortlisted"}), "jobId"),
        (json.dumps({"jobId": IDS[0]}), "status"),
        (json.dumps({"jobId": IDS[0], "status": "shortlisted", "note": None}), "null"),
        (json.dumps([{"jobId": IDS[0], "status": "shortlisted"}]), "object"),
        ("{} {}", "JSON"),
        (json.dumps({"jobId": IDS[0], "status": "shortlisted", "note": "x" * 4001}), "note"),
        ("x" * 20_000, "large"),
    ],
)
def test_invalid_mark_json_stdin_is_rejected_before_network_or_write(
    tmp_path, raw_payload, message
):
    state_file = tmp_path / "job-decisions.json"
    original = b'{"version": 2, "jobs": {}}\n'
    state_file.write_bytes(original)
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark-json-stdin"],
        stdin=StringIO(raw_payload),
        fetch_detail=lambda _job_id: pytest.fail("invalid stdin must not call Pegel"),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert message.lower() in stderr.getvalue().lower()
    assert state_file.read_bytes() == original


def test_mark_json_stdin_rejects_legacy_metadata_flags_before_network_or_write(tmp_path):
    state_file = tmp_path / "job-decisions.json"
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--mark-json-stdin", "--note", "argv value"],
        stdin=StringIO(json.dumps({"jobId": IDS[0], "status": "shortlisted"})),
        fetch_detail=lambda _job_id: pytest.fail("conflicting input must not call Pegel"),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "conflict" in stderr.getvalue().lower()
    assert not state_file.exists()


def test_mark_json_stdin_does_not_echo_an_unknown_control_character_key(tmp_path):
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(tmp_path / "decisions.json"), "--mark-json-stdin"],
        stdin=StringIO(json.dumps({
            "jobId": IDS[0],
            "status": "shortlisted",
            "unknown\x1b[31m": "value",
        })),
        fetch_detail=lambda _job_id: pytest.fail("invalid stdin must not call Pegel"),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert stderr.getvalue() == "Decision error: Mark JSON has unknown fields\n"


def test_committed_mark_cleanup_failure_returns_success_without_inviting_a_blind_retry(
    tmp_path, monkeypatch
):
    state_file = tmp_path / "job-decisions.json"
    lock_file = Path(f"{state_file}.lock")
    lock_fds = []
    real_open = job_decisions.os.open
    real_close = job_decisions.os.close
    stdout = StringIO()
    stderr = StringIO()

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
            patch.setattr(job_decisions.os, "open", track_open)
            patch.setattr(job_decisions.os, "close", fail_lock_close)
            exit_code = pegel_query.main(
                ["--state-file", str(state_file), "--mark-json-stdin"],
                stdin=StringIO(json.dumps({"jobId": IDS[0], "status": "shortlisted"})),
                fetch_detail=lambda _job_id: None,
                now=lambda: "2026-09-01T08:30:00Z",
                stdout=stdout,
                stderr=stderr,
            )

        assert exit_code == 0
        assert "change was saved" in stderr.getvalue().lower()
        assert "inspect" in stderr.getvalue().lower()
        assert "before" in stderr.getvalue().lower()
        assert "decision error" not in stderr.getvalue().lower()
        assert len(json.loads(state_file.read_text())["jobs"][IDS[0]]["history"]) == 1
    finally:
        for fd in lock_fds:
            real_close(fd)


def test_help_describes_private_mark_transport_and_all_saved_status_filtering():
    output = StringIO()

    with redirect_stdout(output), pytest.raises(SystemExit) as raised:
        pegel_query.main(["--help"])

    help_text = output.getvalue().lower()
    assert raised.value.code == 0
    assert "--mark-json-stdin" in help_text
    assert "child argv" in help_text
    assert "direct cli compatibility" in help_text
    assert "any saved status" in help_text


def test_list_history_and_forget_json_envelopes_are_stable_and_offline(tmp_path, monkeypatch):
    state_file = tmp_path / "job-decisions.json"
    complete_record = record_decision(
        state_file,
        IDS[0],
        "shortlisted",
        job=api_job(IDS[0], "Saved role"),
        now="2026-09-01T08:30:00Z",
        event_date="2026-09-01",
    )

    def unexpected_api_call(*_args, **_kwargs):
        raise AssertionError("local reads must not call Pegel")

    monkeypatch.setattr(pegel_query, "fetch", unexpected_api_call)
    monkeypatch.setattr(pegel_query, "fetch_job", unexpected_api_call)

    list_stdout = StringIO()
    assert pegel_query.main(
        ["--state-file", str(state_file), "--list-decisions", "shortlisted", "--json"],
        stdout=list_stdout,
    ) == 0
    assert json.loads(list_stdout.getvalue()) == {
        "data": [complete_record],
        "selection": {"status": "shortlisted", "returned": 1},
    }

    all_stdout = StringIO()
    assert pegel_query.main(
        ["--state-file", str(state_file), "--list-decisions", "all", "--json"],
        stdout=all_stdout,
    ) == 0
    assert json.loads(all_stdout.getvalue())["selection"]["status"] == "all"

    history_stdout = StringIO()
    assert pegel_query.main(
        ["--state-file", str(state_file), "--history", IDS[0].upper(), "--json"],
        stdout=history_stdout,
    ) == 0
    assert json.loads(history_stdout.getvalue()) == {"data": complete_record}

    forget_stdout = StringIO()
    assert pegel_query.main(
        ["--state-file", str(state_file), "--forget", IDS[0].upper(), "--json"],
        stdout=forget_stdout,
    ) == 0
    assert json.loads(forget_stdout.getvalue()) == {
        "data": {"id": IDS[0], "forgotten": True},
    }


def test_history_is_offline_chronological_and_indents_every_metadata_line(tmp_path, monkeypatch):
    state_file = tmp_path / "job-decisions.json"
    record_decision(
        state_file, IDS[0], "offered", job=api_job(IDS[0], "Saved role"),
        now="2026-09-03T08:00:00Z", event_date="2026-09-03",
    )
    record_decision(
        state_file, IDS[0], "applied", job=None,
        now="2026-09-02T10:00:00Z", event_date="2026-09-02",
        note="First line\nStatus : forged",
    )
    record_decision(
        state_file, IDS[0], "interviewing", job=None,
        now="2026-09-02T10:00:00Z", event_date="2026-09-02",
    )
    record_decision(
        state_file, IDS[0], "rejected", job=None,
        now="2026-09-04T09:00:00Z", event_date="2026-09-04",
        rejection_reason="Role closed\nUpdated : forged",
    )

    def unexpected_api_call(*_args, **_kwargs):
        raise AssertionError("history must not call Pegel")

    monkeypatch.setattr(pegel_query, "fetch", unexpected_api_call)
    monkeypatch.setattr(pegel_query, "fetch_job", unexpected_api_call)
    stdout = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(state_file), "--history", IDS[0]],
        fetch_detail=unexpected_api_call,
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "Status   : rejected" in output
    assert output.index("Status   : applied") < output.index("Status   : interviewing")
    assert output.index("Status   : interviewing") < output.index("Status   : offered")
    assert output.index("Status   : offered") < output.rindex("Status   : rejected")
    assert "\n             Status : forged" in output
    assert "\n             Updated : forged" in output
    assert "\nStatus : forged" not in output
    assert "\nUpdated : forged" not in output

    json_stdout = StringIO()
    assert pegel_query.main(
        ["--state-file", str(state_file), "--history", IDS[0], "--json"],
        fetch_detail=unexpected_api_call,
        stdout=json_stdout,
    ) == 0
    assert [
        event["status"] for event in json.loads(json_stdout.getvalue())["data"]["history"]
    ] == ["applied", "interviewing", "offered", "rejected"]


def test_missing_history_returns_one_without_an_api_request(tmp_path, monkeypatch):
    def unexpected_api_call(*_args, **_kwargs):
        raise AssertionError("history must not call Pegel")

    monkeypatch.setattr(pegel_query, "fetch", unexpected_api_call)
    monkeypatch.setattr(pegel_query, "fetch_job", unexpected_api_call)
    stderr = StringIO()

    exit_code = pegel_query.main(
        ["--state-file", str(tmp_path / "missing.json"), "--history", IDS[0]],
        fetch_detail=unexpected_api_call,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 1
    assert stderr.getvalue() == f"No local history exists for {IDS[0]}.\n"
