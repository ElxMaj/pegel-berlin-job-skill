# Pegel Berlin jobs, a Claude Skill

![Pegel Berlin jobs, a Claude skill for truthful Berlin job hunting. A mechanical assistant selects one card from a wall and hands it to a person.](assets/readme-hero.webp)

Find a Berlin startup job and prepare a **truthful** application for it.

Free. Open source. It will never apply on your behalf, never invent a fact about a job, never
fabricate your experience, and never send your CV anywhere.

## What it does

**Pegel is the data layer. This skill is the preparation layer. You apply.**

1. **Find** searches [Pegel](https://pegel.berlin)'s live job list (pulled daily from companies'
   public ATS feeds) with the filters that actually matter in Berlin: *no German required*, *visa
   sponsorship*, *salary disclosed*, stack, seniority, sector.
2. **Fit** reads your CV **locally** and gives you an honest per-role gap analysis. Matches,
   missing and partial are labelled separately. It will not oversell you into a role you will not get.
3. **Tailor** writes a custom CV and cover letter for **one specific role**, truthful to what is
   actually in your CV, in the right shape (tabular Lebenslauf), **in German or English**,
   using a real decision rule rather than a guess.
4. **Prepare** covers interview prep, and an offer check against German employment law: Probezeit,
   notice period (§622 BGB), vacation, EU Blue Card thresholds.

Searches also remember your application timeline across sessions. Roles with any saved status are
hidden from normal results, so each search surfaces roles you have not judged yet. The log stays on
your machine. Here, `passed` means you chose not to pursue the role, never that you passed an
interview stage.

## Why it is different

Generic AI CV tools are built for the US market and get Germany wrong. This one knows:

- the **tabular Lebenslauf** (≤2 pages) and that the **photo is optional, not mandatory**; it is more
  expected at traditional German employers than at an international Berlin startup;
- when an **Anschreiben** is genuinely expected and when a startup's short-answer form replaces it;
- how to **decode an Arbeitszeugnis** (§109 GewO bans hidden codes; they persist anyway);
- **when to apply in English and when in German**: ~56% of Berlin startups run in English, but
  only ~2.7% of German job ads nationally say German isn't required. Berlin startups are the
  exception, not proof that Germany is English-friendly;
- that the **Chancenkarte is a job-*search* permit, not a work permit**, an expensive thing to
  misunderstand;
- the **2026 EU Blue Card thresholds** (€50,700 / €45,934.20), and that meeting the salary bar is
  *not* the same as being eligible.

And because it reads Pegel's live data, it tells you what is **unknown**. If an employer didn't
disclose the salary, it says so instead of inventing a range.

## What it will never do

- Auto-apply or mass-apply. Greenhouse, Workday and LinkedIn all contractually ban automated
  applications, and mass-applying gets people banned. It also doesn't work.
- Invent a salary, visa status, or language requirement. Unknown stays **unknown**.
- Fabricate your experience. No invented employers, dates, tools, degrees, or metrics.
- Send your CV anywhere. It is read locally and stays on your machine.
- Upload your application status, notes, rejection reasons, or contact names.
- Keyword-stuff to game an ATS.

Full policy: [references/trust-policy.md](references/trust-policy.md).

## Install

One line, works with Claude Code, Cursor, Codex and every agent the skills CLI supports:

```bash
npx skills add ElxMaj/pegel-berlin-job-skill
```

Or by hand, for Claude Code specifically:

```bash
git clone https://github.com/ElxMaj/pegel-berlin-job-skill
cp -r pegel-berlin-job-skill ~/.claude/skills/pegel-berlin-jobs
```

Then in Claude Code:

```
/pegel-berlin-jobs
```

Or just ask: *"Find me Berlin backend jobs that don't need German and sponsor visas."*

## Try it

```bash
python3 scripts/pegel_query.py --german not_needed --salary-disclosed --limit 10
python3 scripts/pegel_query.py --tech-tags react,typescript --seniority senior
python3 scripts/pegel_query.py --mark <full-job-id> shortlisted
python3 scripts/pegel_query.py --mark <full-job-id> rejected --date 2026-08-31 --reason "Role was filled"
python3 scripts/pegel_query.py --list-decisions shortlisted
python3 scripts/pegel_query.py --history <full-job-id>
python3 scripts/pegel_query.py --forget <full-job-id>
```

Normal searches exclude every role with a saved status and keep paging until they return the
requested number of unseen roles. Pass `--include-decided` only when you want those roles included
again without deleting their history.

## Local Job Log

The skill stores application history in `~/.local/share/pegel/job-decisions.json` by default, or
under `$XDG_DATA_HOME/pegel/` when that variable is set. You can choose another file with
`PEGEL_DECISIONS_FILE` or the script's `--state-file` option.

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
- Mark: `--mark <full-job-id> <status>` appends an event. Optional mark-only metadata is
  `--date YYYY-MM-DD`, `--note <short-summary>`, `--reason <short-rejection-reason>`,
  `--response-kind human|automated|unknown`, and `--contact-name <name>`. `--reason` is valid only
  with `rejected`.
- List: `--list-decisions all` or `--list-decisions <status>` reads the local file only.
- History: `--history <full-job-id>` reads one chronological local timeline only.
- Forget: `--forget <full-job-id>` removes that role and its complete history.
- Output and location: add `--json` for JSON, and use `--state-file <path>` or
  `PEGEL_DECISIONS_FILE` to override the default file. Run `python3 scripts/pegel_query.py --help`
  for the full search-filter reference.

Only candidate-explicit facts belong in the log. A note or rejection reason is a short summary the
candidate supplied or approved. Never copy raw message bodies, email addresses, attachments, or
mailbox identifiers into it. Silence is not a rejection, and ambiguous outcomes need confirmation.

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

`--mark` returns `{"data": record}` and `--history` returns the same envelope with the events in
chronological order.

```json
{"data": [], "selection": {"status": "all", "returned": 0}}
```

`--list-decisions` returns matching complete records in `data`; `selection.status` is `all` or the
requested status.

```json
{"data": {"id": "<job-id>", "forgotten": true}}
```

`--forget` returns `forgotten: false` when no local record existed.

### Migration and writes

Reading a schema v1 file normalizes it in memory but does not rewrite it. On the first mutation,
the script creates `<decision-file>.v1.bak` with the exact original v1 bytes before writing v2. If
an identical backup already exists, it is reused. If its bytes differ, the mutation fails and
leaves both files alone. Invalid or newer schemas fail without being overwritten.

Mutations take an exclusive local lock; a concurrent mutation fails loudly with a retry message.
Writes use a same-directory temporary file, flush it, then atomically replace the decision file.
On systems that support POSIX modes, newly created data directories use `0700` and local files use
`0600`. No POSIX permission promise is made on Windows.

Listing and history are offline. Marking may make one ordinary read-only request for the public job
UUID to save its title and link. The status and all event metadata remain local and are never API
parameters, request bodies, or headers sent to Pegel. If the snapshot read fails, the event is still
saved without a snapshot.

## Data

Roles come from [Pegel's public API](https://pegel.berlin/api) (60 req/min). Pegel pulls them daily
from companies' own public ATS feeds and never estimates a salary. This skill never scrapes an ATS.

## On the web

The skill has a home page at [pegel.berlin/tools/claude-skill](https://pegel.berlin/tools/claude-skill) with the install command and the trust policy in short form.

## Licence

MIT. Use it, fork it, improve it.
