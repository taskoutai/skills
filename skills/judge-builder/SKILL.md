---
name: judge-builder
description: "Build and run an automated judge for one of the firm's taskout playbooks, on the firm's own machine: GEPA tunes the judge's instructions until it agrees with the firm's reviewers, the judge then reviews every finished job, and the jobs that went wrong become proposed rule changes. Use when a playbook's How it's working tab has enough reviews, to judge new jobs, or to propose rule fixes."
metadata:
  version: "1.0.0"
  generated-by: "taskout"
---

# Judge builder

taskout knows how each job held up only from the jobs a person reviewed. This skill builds a judge that reviews the
rest the way the firm's reviewers do, and turns what goes wrong into proposed rule changes. Everything that reads
the work runs here, on the firm's machine: the work never goes to taskout. What goes to taskout is the judge's
instructions, its verdicts (ids, outcome, cause, rule ids) and proposed rules, and a person approves each.

## What you need

- The jobs folder: each agent saves its finished work in `taskout-jobs/<context_id>/` (the firm plugin tells it
  to). Point `TASKOUT_JOBS_DIR` at the firm's shared folder, or pass `--jobs`.
- The examples file: on the playbook's **How it's working** tab, **Download examples** (people's verdicts, the
  rules of each version, answered questions; no work).
- Python 3.10+, `pip install "gepa==0.1.4" "anthropic>=2.6"`, and the firm's own Claude API key (`ANTHROPIC_API_KEY`).
  Calls use `claude-opus-5-5` unless you pass `--model`. Each judge call is one Claude call: tell the person
  the budget before a run (`--budget`, default 150 calls) and get their go-ahead.

## 1. Build the judge

```
python scripts/build_examples.py --examples taskout-examples.json
python scripts/optimize_judge.py --budget 150
```

`build_examples.py` uses only jobs taskout picked at random for review, and holds a fixed third back. Tell the
person what it printed; if it says there isn't enough yet, stop there. `optimize_judge.py` runs GEPA: the judge
reviews the training jobs, Claude reads where it disagreed with people and why, and rewrites its instructions; the
best instructions are then run once on the held-out jobs. It writes `judge.json`.

Read the instructions in `judge.json` with the person before importing. Then, on the How it's working tab,
**Import a judge**. taskout recomputes how often the judge agrees with people on the held-out jobs from its own
records, and the playbook's owner approves it only when it agrees on at least 8 in 10 and catches at least 8 in 10
of the jobs people sent back or rejected.

## 2. Judge new jobs

```
python scripts/judge_jobs.py --judge judge.json --examples taskout-examples.json
```

Judges the jobs saved since the last run (never the ones it was built from) and writes `judge-verdicts.json`.
Upload it on the How it's working tab (**Upload judge verdicts**). The judge's verdicts show in what to fix,
marked as the judge's; the playbook's headline number stays people's verdicts only. People keep reviewing a
sample: when the judge stops agreeing with them, the tab says so and its verdicts stop counting until you rebuild it.

## 3. Propose rule changes

```
python scripts/propose_rules.py --examples taskout-examples.json --judge judge.json
```

For each rule people (or the judge) said wasn't followed or was wrong in at least 2 jobs, and for work sent back
because no rule covered it, Claude reads those jobs and proposes a revised rule, a new one, or no change. Jobs the
judge was built from are left out. Upload `judge-verdicts.json` first: taskout accepts a change only when every job
it cites is known there as gone wrong. Go through `proposals.json` with the person, then **Import proposed changes**.
Each change arrives as a proposal; once approved and published, the new version can be tried on a share of jobs
before everyone gets it.

## Rules for you

- Never send a job's work, a reviewer's notes or anything from the jobs folder to taskout, or anywhere but the
  Claude calls these scripts make.
- Never edit `judge.json` or `proposals.json` to put in client names, figures or anything from a piece of work.
  The scripts and taskout refuse files that look like they hold an identifier.
- A person decides: you don't import, approve or upload without them.
- See `references/method.md` for how the judge is built and measured.
