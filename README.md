# Pegel Berlin jobs

![Pegel Berlin jobs, a Claude skill for truthful Berlin job hunting. A mechanical assistant selects one card from a wall and hands it to a person.](assets/readme-hero.webp)

An agent skill for finding Berlin startup roles, checking CV fit and preparing an honest
application. A local Job Log remembers which roles you have already considered and what happened
after you applied.

**Pegel supplies the listings. Your AI assistant helps with preparation. You submit the application.**

Free and MIT licensed. The skill includes agent instructions, reference files and a Python query
script. Use it in Claude Code or another compatible agent with file and command-line access.
It is not a desktop application.

```bash
npx skills add ElxMaj/pegel-berlin-job-skill
```

[Install and start](#install) · [Example prompts](#example-prompts) ·
[Local Job Log](#local-job-log) · [Privacy](#privacy)

## What it does

| Step         | What the skill helps with                                                                                                                                              | What you check or decide                                                                              |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Find**     | Query [Pegel](https://pegel.berlin)'s live API by German requirement, stack or seniority. Other filters include sector and disclosed salary.                           | Choose a role to examine. A company visa-support signal does not guarantee sponsorship for that role. |
| **Fit**      | Read a CV file you select and compare it with the actual posting. Separate evidenced matches from gaps; label partial matches as inferences.                           | Confirm missing or ambiguous candidate facts.                                                         |
| **Tailor**   | Draft a CV or cover letter for one selected role, using your real experience. Follow posting signals for English or German and the relevant German application format. | Review the draft, then apply on the employer's site yourself.                                         |
| **Prepare**  | Help with interview questions using the role and available company facts. Dated German employment and immigration references provide context.                          | Verify time-sensitive rules and eligibility with current official sources.                            |
| **Remember** | Record explicit decisions and a dated application history in a local JSON file. Exclude already-considered roles from normal searches.                                 | Confirm what actually happened before it is logged.                                                   |

An undisclosed salary stays undisclosed. Unknown German or visa requirements stay unknown.
The skill instructs the assistant to preserve the employer's posting and never invent candidate
experience. It does not submit applications, fill ATS forms or keyword-stuff a CV.

## Install

You need Python 3 for the query script. The installer command needs Node.js/npm and lets you
select a [supported agent](https://www.skills.sh/docs/cli), including Claude Code, Cursor or Codex.
The skill is free; access to your chosen AI assistant is separate.

```bash
npx skills add ElxMaj/pegel-berlin-job-skill
```

Or by hand, for Claude Code specifically:

```bash
git clone https://github.com/ElxMaj/pegel-berlin-job-skill
mkdir -p ~/.claude/skills
cp -r pegel-berlin-job-skill ~/.claude/skills/pegel-berlin-jobs
```

Then in Claude Code:

```
/pegel-berlin-jobs
```

Other supported agents use their own skill-loading conventions.

## Example prompts

Start with a search, then work on one selected role:

> Find Berlin backend roles that don't need German. Show only roles with disclosed salary.

> Compare this posting with the CV file I selected. Show evidenced matches and gaps before drafting.

> Prepare a cover letter for this role using only facts supported by my CV. Ask about missing details.

After taking an action yourself:

> I submitted this application on 2 October 2026. Record it as applied.

> Show the history for this role and list the applications marked interviewing.

These are example requests, not automatic actions. Preparing a document does not mark a role as
applied. Silence does not mark it rejected. A reply is logged only from facts you supply or approve.

## Use the query script directly

From the installed skill directory or a clone of this repository:

```bash
python3 scripts/pegel_query.py --german not_needed --salary-disclosed --limit 10
python3 scripts/pegel_query.py --tech-tags react,typescript --seniority senior
python3 scripts/pegel_query.py --list-decisions shortlisted
python3 scripts/pegel_query.py --list-decisions applied --json
python3 scripts/pegel_query.py --help
```

Normal searches exclude every role with a saved status and keep paging until they return the
requested number of unseen roles. Pass `--include-decided` only when you want those roles included
again without deleting their history. A search can return fewer roles when no more matches remain.
Comma-separated technology tags mean OR, not AND: `react,typescript` matches either tag.
The [API reference](references/pegel-api.md) explains the filters and response fields.

## Local Job Log

The log is your application record. It is not a Pegel account or a mailbox integration.

| Status         | Meaning                                                                  |
| -------------- | ------------------------------------------------------------------------ |
| `shortlisted`  | Worth considering.                                                       |
| `applied`      | You confirmed that you submitted an application.                         |
| `interviewing` | You confirmed an interview stage.                                        |
| `offered`      | You confirmed an offer.                                                  |
| `accepted`     | You accepted the offer.                                                  |
| `rejected`     | You confirmed a rejection.                                               |
| `withdrawn`    | You withdrew the application.                                            |
| `passed`       | You chose not to pursue the role. It does not mean passing an interview. |

Every explicit status update appends an event. Keep a short approved note or rejection reason when
useful. A sender's name and a `human`, `automated` or `unknown` reply label are optional. The public
log does not store raw emails, email addresses or attachments.

Listing decisions and reading a role's history work offline. Finding fresh roles needs the API.
Marking a role may read its public job ID to save its title and link; the private event fields are
not sent to Pegel.

The skill stores application history in `~/.local/share/pegel/job-decisions.json` by default, or
under `$XDG_DATA_HOME/pegel/` when that variable is set. You can choose another file with
`PEGEL_DECISIONS_FILE` or the script's `--state-file` option.

For a private update, run this command interactively, paste the approved JSON object, then send
end-of-input:

```bash
python3 scripts/pegel_query.py --mark-json-stdin
```

An agent may execute private updates only through a host-provided structural stdin channel. If the
host lacks it, the assistant presents the exact JSON for you to run. Private values must not be
embedded in shell commands or heredocs.

`--forget` removes a role from the active log, but does not erase an existing migration backup.
The command and file-format details are below.

## Privacy

**Pegel does not receive your CV or private Job Log through the query script.** Local storage does
not mean the AI model runs locally.

| Data                              | Where it goes                                                                                                          |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Search filters and public job IDs | Pegel's public API, as ordinary read requests.                                                                         |
| CV content and private log fields | Local files; the query script does not upload them to Pegel.                                                           |
| Content your AI assistant reads   | May be sent to its model provider under that host's settings. The host may also retain a transcript or command output. |

Check your host's settings before asking it to read sensitive files.
[Claude Code's data-flow documentation](https://code.claude.com/docs/en/data-usage) describes its
network boundary. The [skills installer](https://www.skills.sh/docs/cli#telemetry) has its own
telemetry policy.

The [trust policy](references/trust-policy.md) contains the agent's conduct rules and the same
host-processing boundary.

## Technical Job Log reference

<details>
<summary>Commands, JSON format and local-file handling</summary>

The JSON below illustrates the record format; it is not a candidate's actual history.

```json
{
  "version": 2,
  "jobs": {
    "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c": {
      "status": "rejected",
      "updatedAt": "2026-09-03T09:10:00Z",
      "history": [
        {
          "status": "applied",
          "date": "2026-09-01",
          "recordedAt": "2026-09-01T08:30:00Z",
          "note": "Applied on the employer site"
        },
        {
          "status": "rejected",
          "date": "2026-09-03",
          "recordedAt": "2026-09-03T09:10:00Z",
          "rejectionReason": "Role was filled",
          "responseKind": "human",
          "contactName": "Alex"
        }
      ],
      "title": "Founder’s Associate",
      "company": "NetBird",
      "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6"
    }
  }
}
```

The eight statuses are `shortlisted`, `applied`, `interviewing`, `offered`, `accepted`, `rejected`,
`withdrawn`, and `passed`. Each `--mark` appends an event. `status` is derived from the latest dated
event, while `updatedAt` records the latest write. Event `date` is the factual date and `recordedAt`
is when the event was saved. `note`, `rejectionReason`, `responseKind`, and `contactName` are optional.

### Commands

- Search: use the documented filters, plus `--include-decided` to include roles already in the log.
- Private mark: `--mark-json-stdin` reads one JSON object with required `jobId` and `status` fields
  and optional `date`, `note`, `rejectionReason`, `responseKind`, and `contactName` fields. It is
  bounded to 16 KiB and keeps those values out of child argv.
- Legacy mark: `--mark <full-job-id> <status>` remains a direct CLI compatibility input. Optional
  mark-only metadata is
  `--date YYYY-MM-DD`, `--note <short-summary>`, `--reason <short-rejection-reason>`,
  `--response-kind human|automated|unknown`, and `--contact-name <name>`. `--reason` is valid only
  with `rejected`. Legacy values may be visible in process arguments and shell history.
- List: `--list-decisions all` or `--list-decisions <status>` reads the local file only.
- History: `--history <full-job-id>` reads one chronological local timeline only.
- Forget: `--forget <full-job-id>` removes that role and its complete history from the active log.
  It does not erase an existing schema v1 migration backup.
- Output and location: add `--json` for JSON, and use `--state-file <path>` or
  `PEGEL_DECISIONS_FILE` to override the default file. Run `python3 scripts/pegel_query.py --help`
  for the full search-filter reference.

The stdin payload is exactly one object. Omit optional fields instead of sending `null`:

```json
{
  "jobId": "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
  "status": "rejected",
  "date": "2026-08-31",
  "note": "Follow up next quarter",
  "rejectionReason": "Role was filled",
  "responseKind": "human",
  "contactName": "Alex Martin"
}
```

A candidate can run `python3 scripts/pegel_query.py --mark-json-stdin`, paste the approved object,
then send end-of-input. An agent may execute it only when its host supplies a separate structural
stdin channel.

Only candidate-explicit facts belong in the log. A note or rejection reason is a short summary the
candidate supplied or approved. Never copy raw message bodies, email addresses, attachments, or
mailbox identifiers into it. Silence is not a rejection, and ambiguous outcomes need confirmation.
Stdin transport avoids putting private mark values in child argv. It does not prevent the host from
capturing its transcript or output, so use only a host-provided structural stdin channel for agent
execution.

### Local JSON success envelopes

Search JSON is unchanged and is documented in [the API reference](references/pegel-api.md). Local
commands use these envelopes, where `record` is the v2 job object shown above:

```json
{
  "data": {
    "id": "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c",
    "status": "shortlisted",
    "updatedAt": "2026-09-01T08:30:00Z",
    "history": [
      {
        "status": "shortlisted",
        "date": "2026-09-01",
        "recordedAt": "2026-09-01T08:30:00Z"
      }
    ],
    "title": "Founder’s Associate",
    "company": "NetBird",
    "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6"
  }
}
```

`--mark-json-stdin` and legacy `--mark` return `{"data": record}`. `--history` returns the same
envelope with the events in chronological order.

```json
{ "data": [], "selection": { "status": "all", "returned": 0 } }
```

`--list-decisions` returns matching complete records in `data`; `selection.status` is `all` or the
requested status.

```json
{ "data": { "id": "<job-id>", "forgotten": true } }
```

`--forget` returns `forgotten: false` when no local record existed.

### Migration and writes

Reading a schema v1 file normalizes it in memory but does not rewrite it. On the first mutation,
the script creates `<decision-file>.v1.bak` with the exact original v1 bytes before writing v2. If
an identical backup already exists, it is reused only when it is an independent private regular
file. Symlinks, non-regular entries, the same underlying file or a hard link, and group- or
other-accessible POSIX files are rejected without changing either file. Invalid or newer schemas
fail without being overwritten. Schema v2 also rejects unknown root fields instead of silently
dropping them during a later mutation.

The `.v1.bak` file remains sensitive recovery data. It is never automatically rewritten or deleted,
including by `--forget`, which removes data only from the active log.

Mutations take an exclusive local lock; a concurrent mutation fails loudly with a retry message.
An existing lock is reused only when `lstat`, a no-follow open where available, and `fstat` confirm
it is the same independent regular file with one link. Symlinks, hard links, non-regular entries,
and replacement races are rejected before locking or writing a Windows lock byte.
Writes use a same-directory temporary file, flush it, then atomically replace the decision file.
On systems that support POSIX modes, newly created data directories use `0700` and local files use
`0600`. No POSIX permission promise is made on Windows.

Listing and history are offline. Marking may make one ordinary read-only request for the public job
UUID to save its title and link. The status and all event metadata remain local and are never API
parameters, request bodies, or headers sent to Pegel. If the snapshot read fails or returns malformed
optional snapshot fields, the event is still saved without a snapshot.

</details>

## Data and availability

Roles come from [Pegel's public API](https://pegel.berlin/api) (60 requests/minute per IP), sourced
from employers' public ATS feeds. The skill reads that API and the selected posting on Pegel;
it does not scrape an ATS. A listing is an observed posting, not a guarantee that a role will remain
open or that an application will succeed.

This repository contains the public agent skill and JSON Job Log. The desktop companion is
maintained privately and is unreleased. This installation does not include a desktop installer,
SQLite companion integration or raw correspondence storage.

## On the web

The skill has a home page at [pegel.berlin/tools/claude-skill](https://pegel.berlin/tools/claude-skill) with the install command and the trust policy in short form.

## Licence

MIT. Use it, fork it, improve it.
