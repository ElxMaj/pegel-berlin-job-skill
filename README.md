# Pegel Berlin jobs, a Claude Skill

![A mechanical arm pulls one card from a wall of identical pinned job cards and hands it to a person, who takes it with their own hand. Pen-and-ink engraving on cream paper.](assets/hero.webp)

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
```

## Data

Roles come from [Pegel's public API](https://pegel.berlin/api) (60 req/min). Pegel pulls them daily
from companies' own public ATS feeds and never estimates a salary. This skill never scrapes an ATS.

## On the web

The skill has a home page at [pegel.berlin/tools/claude-skill](https://pegel.berlin/tools/claude-skill) with the install command and the trust policy in short form.

## Licence

MIT. Use it, fork it, improve it.
