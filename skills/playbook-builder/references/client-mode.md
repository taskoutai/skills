# Client mode: one client's rules

The rules for **one client**: what its own documents say to do and what the team's past work for it
shows, where that is specific to this client. An agent loads them for this client's work, on top of the
team's service rules, which they replace where they differ. The ground rules in SKILL.md apply
unchanged, as do the check script and the export.

```
- [ ] 1. Agree scope with the user
- [ ] 2. Read the client's documents
- [ ] 3. Read the client's past engagements
- [ ] 4. User confirms the candidate rules (stop and wait)
- [ ] 5. Write playbook.json
- [ ] 6. Scrub, then run the check script until it passes
- [ ] 7. Review the rules with the user
- [ ] 8. Test on a kept-back engagement (if there is one)
- [ ] 9. Export for the team's agents
- [ ] 10. Hand over
```

## 1. Agree scope with the user

Ask for, and do not guess:

- **The service**: which kind of work for this client these rules are for (individual return,
  bookkeeping, payroll). One service per build: an agent doing this client's payroll must not get
  rules learned from its tax return. If `references/task.md` exists, it is that service; otherwise
  ask the user to name it and, if the team uses taskout, to download the skill from that service's
  page (or to choose the service when importing).
- **The client's reference**: the firm's own id for the client (for example its number in the practice
  management system, `C-1042`). Never its name and never a tax identifier. It is required: it is
  how taskout and the agents know whose rules these are.
- **The client's folder**: its standing documents (engagement letters, instructions and correspondence,
  entity documents, elections, agreements such as loan covenants or operating agreements, prior-year
  notes), and its past engagements for **this service**, one subfolder each (`documents/` and
  `deliverables/`) with the tax year of each. Leave out its engagements for other services.
- **Which past engagement to keep back for the test** (step 8): the latest one, when there are at least
  two. With one or none, there is no test of practice; say so at hand-over.
- **The team's service playbook, if it has one** (a `playbook.json`: the team's own, or downloaded
  from taskout with **Download**, as `playbook.json`). Read its topics and positions only, to know
  what the team does by default; it is how you know which of its rules a client rule replaces.
- Confirmation that they may process these documents with this agent (as in SKILL.md, step 1).

Create `.playbook-builder/` inside the client's folder with `notes.md`, `report.md` and
`redact.txt`. One client, one working folder.

## 2. Read the client's documents

Read each standing document and note every passage that tells the team what to do, or not do, for
this client in this service, or in all of its work. Record each in `report.md` with a `d` id: `d1: <file> / page 2 / section 3`. Look for:

- **Scope**: what is in and what is out (a return billed separately, a state not engaged, services
  the letter excludes).
- **The client's instructions**: who gets drafts and in what order, deadlines, formats, approvals,
  who signs.
- **Elections and standing positions**: an election in force and since when, a method the client
  adopted.
- **Agreements and constraints**: what a covenant, a partnership agreement or a regulator requires of
  the work (a reviewed statement, a ratio to report, a consent before filing).
- **Facts that change the work**: a fiscal year end, an accounting method, a state of residence, only
  where they change what the team does.

For each, note whether it is about this service only (most are) or about all of the client's work (the
engagement letter's terms for every service, who signs for the client, how to reach it). For each,
note the tax years it covers: the engagement letter's year, the year an election took
effect, an agreement's term. Where two documents disagree, the later one governs only if it says so;
otherwise ask the user. A document says what was agreed or instructed; it is not proof of what is
legally correct.

## 3. Read the client's past engagements

Outline each build engagement as [method.md](method.md) (Pass 1) describes, citing with `c` ids.
Then look for what this client's work shows: the same treatment year after year, a choice the service
playbook makes differently, a step the team always adds for this client. For each, count
`support_matters` yourself: this client's build engagements that show it. A treatment seen once is
"seen once" in its comment, or left out. Skip what the service playbook already says and this
client follows: the client's rules hold only what is specific to it.

## 4. Checkpoint: the user confirms the candidate rules

Show the user one list: the rules from the documents (with the document and its years), then the
rules from practice (with their counts), and for each whether it replaces one of the service
playbook's rules (by its topic) and whether it is for this service only or for all of the client's
work. Ask them to confirm, reword, drop or add, and whether each document
is still in force. **Stop here until they answer.** Their wording is authoritative from now on.

## 5. Write playbook.json

As [playbook-format.md](playbook-format.md) describes, with these differences (example:
[../assets/example-client-playbook.json](../assets/example-client-playbook.json)):

- `client_ref`: the client's reference. `title`: the user's words, for example "C-1042: individual
  return".
- `task_id`: the service's id from `references/task.md`, if there is one. Every rule holds for that
  service only. A rule the user confirmed is for all of the client's work: `all_services: true`.
- `precedent_count`: this client's build engagements (0 if it has none yet).
- Each rule that replaces a service rule: `replaces` set to that rule's topic, exactly as the service
  playbook has it, and its `activity_type`. Any other rule: an activity type of its own, such as
  `client.scope`, `client.deadlines` or `client.general`.
- Each position rests on evidence: `doc_refs` (the `d` ids of the passages that state it), or
  `support_matters` above 0 with its `citation_refs` (the engagements that show it), or both. A
  position with neither is refused (`NO_EVIDENCE`).
- A red line of the client's (a document says never to do something) is an `unacceptable` position.
- `tax_years` on a rule that holds only for some years: `2025`, `2023-2025`, `2026-` (from 2026 on).
- `escalation`: who decides for this client when no position fits, by role ("the client's
  relationship partner").
- No `workflow`, `firm_skills` or `client_exceptions`: the whole file is the client's.

## 6. Scrub, then check

Write `redact.txt` as SKILL.md (step 6) describes, with these differences for one client:

- List the client's name and every other party's name (its people, banks, counterparties), personal
  identifiers, account numbers, addresses, and one year's results (its income, its tax due, its
  balances). Write "the client" in the rules; `client_ref` says which client.
- Keep the client's standing parameters in the rules, and out of `redact.txt`: its fiscal year end,
  a fee cap, materiality, a covenant ratio, an election's first year. These are what make its rules
  its own.

```bash
python3 scripts/check_playbook.py playbook.json --redact .playbook-builder/redact.txt --report .playbook-builder/report.md --service <service playbook.json>
```

Leave out `--service` when there is no service playbook. With it, the script checks that every
`replaces` is one of its topics (`REPLACES_NOT_FOUND`). Fix each finding and run it again, as in
SKILL.md (step 8).

## 7. Review the rules with the user

Go through the rules from documents first: for each, the passage (from `report.md`) and the years it
covers, so the user confirms the document says what the rule says and is still in force. Then the
rules from practice, with their counts, and the replacements: for each, the service rule's position
beside the client's. Change the playbook only as they say, then run the check script again.

## 8. Test on a kept-back engagement

Only the rules from practice can be tested: predict, from the kept-back engagement's inputs and the
client's documents, which position each of those rules applies, before reading its deliverables, then
read what the team did. Do it exactly as SKILL.md (step 10) describes, including the user confirming
each reading, and add `local_test` with results for those rules only. A rule from a document is
checked against the document in step 7 instead.

## 9. Export for the team's agents

As SKILL.md (step 11), with the name `client-<reference in lowercase with hyphens>` unless the user
chooses another. The export says the rules are for this client only and replace the team's rules
where they say so.

## 10. Hand over

Tell the user, briefly: how many rules came from documents and how many from practice, which replace a
service rule, which hold only for some tax years, what you left out and why, and the test (or that
there was none). Then:

- Without taskout: the agent gets the client's skill alongside the service skill for this client's work.
- With taskout: on the client's page, **Rules**, **Import client rules**, choose `playbook.json` and the
  service (taken from the file's `task_id` when it has one). Each
  rule arrives as a proposal for the client's relationship owner (or an admin) to approve, then
  **Publish**; from then on agents get them in this client's jobs for that service (and those marked
  `all_services` in all of its jobs). A rule that replaces a service rule
  shows on that rule. Topics the client's rules already have are skipped: change those in taskout.
- Next year, when a new engagement letter or tax year arrives: run client mode again on the new
  documents, starting from this `playbook.json`, and keep `.playbook-builder/` here: it is the
  evidence behind each rule.
