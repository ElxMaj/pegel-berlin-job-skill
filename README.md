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

Searches also remember your decisions across sessions. Roles marked `shortlisted`, `applied` or
`passed` are hidden from normal results, so each search surfaces roles you have not judged yet.
Here, `passed` means you chose not to pursue the role. Shortlists remain available locally.

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
python3 scripts/pegel_query.py --list-decisions shortlisted
python3 scripts/pegel_query.py --forget <full-job-id>
```

Normal searches exclude every role with a saved verdict and keep paging until they return the
requested number of unseen roles. Pass `--include-decided` only when you want those roles included
again without deleting their decisions.

## Local decisions

The skill stores decisions in `~/.local/share/pegel/job-decisions.json` by default, or under
`$XDG_DATA_HOME/pegel/` when that variable is set. You can choose another file with
`PEGEL_DECISIONS_FILE` or the script's `--state-file` option.

```json
{
  "version": 1,
  "jobs": {
    "f623bce6-6cf2-432e-a3d0-5e9f70ebdc3c": {
      "verdict": "shortlisted",
      "updatedAt": "2026-09-01T08:30:00Z",
      "title": "Founder’s Associate",
      "company": "NetBird",
      "pegelUrl": "https://pegel.berlin/jobs/founder-s-associate-f623bce6"
    }
  }
}
```

The directory is created with `0700` permissions and the file with `0600` permissions on systems
that support POSIX modes. Writes are atomic. Invalid or newer schemas fail loudly instead of being
overwritten. Listing saved decisions is offline. Marking one may read the public job endpoint once
to save its title and link, but the verdict is never included in an API request and never leaves
your machine.

## Data

Roles come from [Pegel's public API](https://pegel.berlin/api) (60 req/min). Pegel pulls them daily
from companies' own public ATS feeds and never estimates a salary. This skill never scrapes an ATS.

## On the web

The skill has a home page at [pegel.berlin/tools/claude-skill](https://pegel.berlin/tools/claude-skill) with the install command and the trust policy in short form.

## Licence

MIT. Use it, fork it, improve it.
