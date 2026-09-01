# Pegel Job Log v2 Design

**Date:** 2026-09-01
**Repository:** `ElxMaj/pegel-berlin-job-skill`
**Scope:** The first PR in the approved local-first roadmap

## Goal

Turn the existing latest-verdict file into a private application log that preserves dated history,
supports a small honest application lifecycle, and exposes stable machine-readable commands for a
future companion client. Existing users keep their saved decisions and existing search behavior.

## Product boundary

The Job Log remains candidate-owned local state. Pegel receives no status, date, contact, rejection
reason, or note in a URL, header, or request body. The skill records an event only after the
candidate explicitly states it. It never infers rejection from silence or from fetched content.

This PR does not store email messages, email addresses, attachments, or mailbox identifiers. A
candidate may save a short private note in their own words. Catalogue synchronization, ETag storage,
and similar-role ranking belong to the later approved PRs because they depend on a public catalogue
contract, not the private Job Log.

## Status vocabulary

The log supports these current statuses:

| Status | Meaning |
|---|---|
| `shortlisted` | The candidate wants to keep the role for later. |
| `applied` | The candidate confirms that they submitted an application. |
| `interviewing` | The candidate confirms that an interview process has started. |
| `offered` | The employer made an offer. |
| `accepted` | The candidate accepted an offer. |
| `rejected` | The employer ended the candidacy. |
| `withdrawn` | The candidate stopped pursuing the role after applying. |
| `passed` | The candidate chose not to pursue the role. It never means passing an interview. |

`shortlisted`, `applied`, and `passed` keep their existing meanings. Search excludes every job ID in
the log, regardless of its current status, unless `--include-decided` is requested. Shortlists remain
available through `--list-decisions shortlisted`.

## Storage contract

The existing JSON file remains the storage format and path. Schema v2 has one record per full Pegel
job UUID:

```json
{
  "version": 2,
  "jobs": {
    "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c": {
      "status": "rejected",
      "updatedAt": "2026-09-01T14:30:00Z",
      "title": "Founder’s Associate",
      "company": "NetBird",
      "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6",
      "history": [
        {
          "status": "shortlisted",
          "date": "2026-08-20",
          "recordedAt": "2026-08-20T09:00:00Z"
        },
        {
          "status": "applied",
          "date": "2026-08-24",
          "recordedAt": "2026-08-24T16:10:00Z",
          "note": "Applied through the employer form"
        },
        {
          "status": "rejected",
          "date": "2026-09-01",
          "recordedAt": "2026-09-01T14:30:00Z",
          "rejectionReason": "The team chose a candidate with more domain experience",
          "responseKind": "human",
          "contactName": "Example Recruiter"
        }
      ]
    }
  }
}
```

Each explicit mark, through preferred `--mark-json-stdin` or legacy `--mark`, appends one event.
Repeating a status is allowed because a candidate can have multiple interview steps or add a later
factual update. `date` is the preferred stdin field for the event's calendar date and defaults to
the current UTC date. Legacy `--date YYYY-MM-DD` also supports truthful backfill. `recordedAt` is
the automatic UTC timestamp at which the command wrote the event.

The current `status` is derived from the event with the latest `date`; ties resolve by `recordedAt`
and then append order. Backfilling an older event therefore preserves the genuinely current status.
`updatedAt` is the latest store-modification timestamp, independent of the event date.

Optional event metadata is omitted when absent:

- `note`, available on every event, maximum 4,000 characters;
- `rejectionReason`, available only for `rejected`, maximum 1,000 characters;
- `responseKind`, one of `human`, `automated`, or `unknown`;
- `contactName`, maximum 200 characters.

Names, reasons, and notes are accepted only from an explicit candidate-approved mark. The preferred
agent path is one bounded, closed-schema JSON object through `--mark-json-stdin`, using a structural
stdin channel so private values do not enter child argv. Legacy `--mark` flags remain process-visible
direct CLI compatibility inputs. Stdin transport does not prevent host transcript or output capture.
The skill never derives metadata from a job description or a guessed application outcome.
Validation rejects missing required fields, explicit nulls, unknown fields, NUL, terminal escape
characters, invalid dates, invalid enums, and oversized text. Newlines and tabs are allowed in notes
and reasons, then rendered with safe indentation in text output.

The schema v2 root is closed to `version` and `jobs`. Unknown root fields fail validation so a
read-modify-write transaction cannot silently erase data it does not understand. Schema v1 remains
limited to its existing compatibility contract.

## Migration and durability

Schema v1 remains readable. A v1 record becomes one v2 history event whose status comes from
`verdict`, whose `date` is the date portion of `updatedAt`, and whose `recordedAt` is the original
`updatedAt`. Read-only listing performs this normalization in memory and does not modify the file.

The first mutation of a v1 file performs these steps under the store lock:

1. Read and validate the exact v1 bytes.
2. Create an adjacent `job-decisions.json.v1.bak` with private permissions using exclusive creation.
3. If that backup already exists, continue only when it is an independent private regular file and
   its bytes match the current v1 file. Reject symlinks, non-regular entries, the same underlying
   file or a hard link, and group- or other-accessible POSIX files.
4. Write schema v2 to a temporary private file and atomically replace the original.

Any backup, lock, serialization, permission, or replace failure before commit becomes a concise
`DecisionStoreError`. The original file remains untouched when migration cannot complete.
The sensitive `.v1.bak` recovery file is never automatically rewritten or deleted. `--forget`
removes a role only from the active log and does not erase an existing migration backup.

Writes use one cross-platform advisory lock file beside the store. Unix uses `fcntl`; Windows uses
`msvcrt`. A second writer fails cleanly rather than silently losing an event. The lock file contains
no personal data and remains available for reuse after release.
Creation is exclusive. Reuse requires an independent regular file with one link, verified with
`lstat`, a no-follow open where available, and `fstat`. Symlinks, hard links, non-regular entries,
and replacement races fail before lock acquisition or any Windows lock-byte write.
An unlock error followed by a successful descriptor close does not turn a committed mutation into
failure. A descriptor-close failure after commit raises the distinct
`DecisionStoreCommittedError` for library callers. The CLI returns success with a warning that the
change was saved and local history must be inspected before another update. Cleanup never masks a
primary body error.

## Command contract

Existing commands remain valid:

```bash
python3 scripts/pegel_query.py --mark <job-id> shortlisted
python3 scripts/pegel_query.py --list-decisions shortlisted
python3 scripts/pegel_query.py --forget <job-id>
```

The preferred private mark action and new history command use the same script:

```bash
python3 scripts/pegel_query.py --mark-json-stdin
python3 scripts/pegel_query.py --history <job-id>
```

The stdin object requires `jobId` and `status`; `date`, `note`, `rejectionReason`, `responseKind`,
and `contactName` are optional but cannot be null when present. Unknown fields are rejected.
Legacy `--reason`, `--response-kind`, `--contact-name`, `--note`, and `--date` flags are valid only
with `--mark`; `--reason` additionally requires `rejected`. Invalid combinations fail before any
API request or local write.

The optional public detail snapshot is validated at the fetch boundary. A malformed title, company
shape or name, or Pegel URL becomes a `PegelApiError`; the explicit event is saved without a snapshot
and the request still contains only the public UUID.

`--json` becomes a supported contract for every local action:

- mark: `{ "data": <complete job-log record including id> }`;
- list: `{ "data": [...], "selection": { "status": <filter>, "returned": <count> } }`;
- history: `{ "data": <complete job-log record including id> }`;
- forget: `{ "data": { "id": <uuid>, "forgotten": <boolean> } }`.

Search JSON remains byte-shape compatible with the current `data`, `pagination`, and `selection`
envelope. Human-readable commands continue to print the current status and add a chronological
timeline for `--history`.

## Files and responsibilities

- `scripts/job_decisions.py`: schema validation, v1 normalization, current-status derivation,
  migration backup, cross-platform lock, atomic persistence, and pure list/history operations.
- `scripts/pegel_query.py`: CLI parsing, invalid-combination rejection, optional public snapshot
  read, text rendering, and JSON envelopes.
- `evals/test_job_decisions.py`: schema, migration, history, status derivation, validation,
  durability, and locking behavior.
- `evals/test_query_workflow.py`: command compatibility, network boundaries, JSON output, and
  end-to-end local workflow.
- `SKILL.md`, `README.md`, `references/trust-policy.md`, and `references/pegel-api.md`: agent
  behavior, user instructions, privacy promise, and response contract.
- `.github/workflows/ci.yml`: the existing test gate runs on Ubuntu, macOS, and Windows with Python
  3.11 so path, replacement, and lock behavior are exercised on all supported desktop families.

No third-party Python dependency is added.

## Verification

Implementation follows test-first cycles. The required gates are:

1. Every new behavior is observed failing before production code is written.
2. Existing 56 tests remain green throughout.
3. Migration preserves every v1 value and the exact original bytes in the backup.
4. No metadata from stdin or a legacy process argument reaches a mocked Pegel API request; only the
   normalized public UUID may reach the detail reader.
5. A backfilled older event does not replace a newer current status.
6. Corrupt, newer, control-character-bearing, oversized, or concurrently written state fails loud.
7. Text and JSON workflows pass on Linux, macOS, and Windows CI.
8. Skill pressure scenarios confirm the agent records only explicit outcomes, never stores raw email,
   and never turns `passed` into an interview result.

## Later PR boundaries

The next Pegel repository PR will expose a documented versioned lightweight catalogue with ETag and
freshness metadata. A subsequent skill PR will refresh that public cache conditionally and compute
explainable similar roles from role type, skills, seniority, and practical requirements. The private
Job Log and public catalogue remain separate files and separate trust domains.
