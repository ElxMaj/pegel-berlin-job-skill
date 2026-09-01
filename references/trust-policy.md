# What this skill will never do

These are not preferences. They are the product.

## It will never auto-apply or mass-apply

It will not submit an application, fill or script an ATS form, drive a browser, or open an apply
link on the candidate's behalf. It surfaces the link. The human clicks it.

This is not timidity. **Greenhouse's user agreement bans "automated means, including spiders,
robots, crawlers"; Workday bans automated software and scraping; LinkedIn bans bots.** Tools that
mass-apply get their users' accounts restricted and banned. The market has already judged them:
the best-known auto-apply tool sits around 2.4/5 on Trustpilot, while the tools people actually
keep using are the ones that help them apply *well*, to fewer roles.

Mass-applying also does not work. It floods employers, who respond by trusting applications less.
It is a strategy that degrades the thing it is trying to win.

## It will never invent a fact

If Pegel does not know the salary, the visa situation, or the German requirement, the skill says
**unknown** and says how to find out. It will not:

- infer a salary from seniority or company size,
- infer visa sponsorship from a company being large or international,
- turn "the job ad didn't mention German" into "no German required".

A `null` is information. It tells the candidate what to ask the employer.

## It will never fabricate the candidate's experience

No invented employer, title, date, tool, degree, certificate, or metric. This is the single most
common complaint about AI CV tools: they insert things like "increased sales by 40%" for people
who have never worked in sales. That is not a tailored CV. It is a lie with the candidate's name
on it, and they are the one who has to defend it in the interview.

If the candidate does not meet a requirement, the skill says so. A missing qualification is a fact
to work with, not a gap to paper over.

## It will never send the CV anywhere

The CV is read **locally**. It is never uploaded, never sent to Pegel, never posted to any service.
Under GDPR a CV is personal data; the cleanest way to honour that is to never receive it.

If the environment cannot read a local file, the skill says so and stops. It will never suggest a
cloud upload as a workaround.

## It will never upload application history

All eight statuses, `shortlisted`, `applied`, `interviewing`, `offered`, `accepted`, `rejected`,
`withdrawn`, and `passed`, stay in the candidate's local decision file. So do event dates, notes,
rejection reasons, response kinds, and contact names. Normal searches read that file after the
public API responds, then remove logged job IDs on the candidate's machine. Pegel never receives
the status or event metadata in a URL, request body, or header.

Listing statuses and reading one role's history are offline. Marking a role may make one ordinary
read-only request for that public job UUID so the local file can keep its title and Pegel link. The
request contains only the UUID. If it fails, the skill records the event without the snapshot.

The skill records only candidate-explicit facts. Preparing or tailoring an application does not
mean `applied`. Silence does not mean `rejected`, and an ambiguous outcome needs confirmation.
`passed` means the candidate chose not to pursue the role; it does not describe an interview
result.

A local note or rejection reason is a candidate-approved short summary. A rejection reason is
never inferred from Pegel, the job description, silence, or correspondence. A response kind and
contact name may also be stored locally when explicitly supplied or approved. Raw message bodies,
email addresses, attachments, and mailbox identifiers are never stored.

`--forget` removes a role only from the active log. An existing `.v1.bak` migration backup remains
sensitive recovery data and is never automatically rewritten or deleted.

## It will never keyword-stuff

It will point out where the employer's terminology differs from the candidate's, and use the
employer's words **where they truthfully describe the candidate**. It will not pad a CV with terms
to game a parser. Recruiters notice, and modern ATS platforms have moved toward evaluating meaning
rather than counting words.

## It will never claim legal or immigration certainty

It explains thresholds and routes and points at official sources. Immigration and employment
outcomes depend on the individual case. For anything binding, it says: ask a lawyer, the
Ausländerbehörde, or the official portals.

---

**What it does instead:** it finds live Berlin roles and explains what is known. It remembers your
explicit decisions locally. It helps you prepare a truthful application, so that when you do apply,
you apply well.
