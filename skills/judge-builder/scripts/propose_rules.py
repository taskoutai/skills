#!/usr/bin/env python3
"""Propose changes to the playbook's rules from the jobs that went wrong, and write proposals.json.

    python scripts/propose_rules.py --examples taskout-examples.json [--judge judge.json] [--jobs taskout-jobs] [--out proposals.json]

GEPA's reflection step, applied to the rules: for each rule that people (or the approved judge) said was not
followed or was wrong, and for the work sent back because no rule covered it, Claude reads those jobs' work, what
went wrong, the reviewers' notes and the questions agents asked people about the rule, and proposes a revised or
new rule, or no change. Jobs the judge was built from are left out, so the judge and the rules are never tuned on
the same jobs. Import proposals.json on the playbook's How it's working tab: every change arrives as a proposal a
person approves, and a new version can be tried on a share of jobs before everyone gets it.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge_common import (  # noqa: E402
    DEFAULT_MODEL,
    SKILL_VERSION,
    claude_json,
    is_failure,
    jobs_dir,
    load_examples,
    load_job,
    read_json,
    render_rules,
    scan,
    write_json,
)

MIN_JOBS = 2
MAX_JOBS_SHOWN = 8
WORK_SHOWN = 6_000
JUDGED_DIR = Path(".judge-builder/judged")

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["revise", "new", "none"]},
        "topic": {"type": "string"},
        "guidance": {"type": "string"},
        "escalation": {"type": "string"},
        "positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"tier": {"type": "string", "enum": ["preferred", "fallback", "unacceptable"]}, "text": {"type": "string"}, "conditions": {"type": "string"}},
                "required": ["tier", "text", "conditions"],
                "additionalProperties": False,
            },
        },
        "why": {"type": "string"},
    },
    "required": ["action", "topic", "guidance", "escalation", "positions", "why"],
    "additionalProperties": False,
}

SYSTEM = """You maintain an accounting firm's playbook: the rules its people and agents follow for one kind of work.
Each rule has a preferred position, fallbacks with the conditions under which they apply, red-line (unacceptable)
positions, and when to ask a person. You are shown jobs whose work the firm's reviewers did not accept, and why.
Propose the smallest change to the rules that would have made those jobs come out right, or no change when the
rule is right and the work simply didn't follow it.

Write the rule as general practice for any client. Never include a client's name, a person's name, a figure, a
date, an identifier, a reference or a quote from the work. A person at the firm reviews every proposal."""


def failures(examples: dict, judged_dir: Path, exclude: set[str]) -> list[dict]:
    """Jobs that went wrong: a person's verdict where there is one, else the approved judge's (kept on this machine)."""
    out, seen = [], set()
    for v in examples.get("verdicts", []):
        if v["context_id"] in exclude:
            continue
        seen.add(v["context_id"])
        if is_failure(v["verdict"]) or v["verdict"] == "accepted_with_changes":
            if v.get("cause") in ("rule_broken", "rule_wrong", "rule_missing"):
                out.append({**v, "by": "person"})
    if judged_dir.is_dir():
        for f in sorted(judged_dir.glob("ctx_*.json")):
            j = read_json(f)
            if j["context_id"] in exclude or j["context_id"] in seen:
                continue
            if is_failure(j["verdict"]) and j.get("cause") in ("rule_broken", "rule_wrong", "rule_missing"):
                out.append({**j, "by": "judge"})
    return out


def groups(fails: list[dict], current_rule_ids: set[str]) -> dict[tuple[str, str], list[dict]]:
    g: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in fails:
        if f["cause"] == "rule_missing":
            g[("rule_missing", "")].append(f)
        else:
            for r in f.get("defect_rule_ids") or []:
                if r in current_rule_ids:
                    g[(f["cause"], r)].append(f)
    return {k: v for k, v in g.items() if len(v) >= MIN_JOBS}


def prompt_for(key: tuple[str, str], jobs: list[dict], rules: list[dict], root: Path, escalations: list[dict]) -> str:
    cause, rule_id = key
    rule = next((r for r in rules if r["id"] == rule_id), None)
    head = {
        "rule_broken": "Reviewers said this rule was not followed. Is the rule unclear, or missing a condition, or is it fine as is?",
        "rule_wrong": "Reviewers said the work followed this rule and was still wrong. Revise the rule.",
        "rule_missing": "Reviewers sent this work back for something no rule covers. Propose a new rule, or none if these jobs share no single practice.",
    }[cause]
    parts = [head, "", "# The playbook's rules now", render_rules(rules)]
    if rule:
        parts += ["", f"# The rule in question: {rule['topic']} (rule {rule['id']})"]
    asked = [e for e in escalations if e.get("answer") and (not rule_id or e.get("rule_id") == rule_id)]
    if asked:
        parts += ["", "# Questions agents asked people about this, and the answers"]
        parts += [f"- Q: {e['question']}\n  A: {e['answer']}" for e in asked[:10]]
    parts += ["", "# The jobs"]
    for i, j in enumerate(jobs[:MAX_JOBS_SHOWN], 1):
        local = load_job(root, j["context_id"])
        work = (local or {}).get("work", "(the work isn't on this machine)")[:WORK_SHOWN]
        notes = (local or {}).get("notes", "")
        verdict = j["verdict"].replace("_", " ")
        parts += [f"## Job {i}: {verdict} by {'the firm reviewer' if j['by'] == 'person' else 'the approved judge'}" + (" (severe)" if j.get("severe") else ""), work]
        if notes:
            parts += [f"Reviewer's notes: {notes}"]
        if j.get("reason"):
            parts += [f"Judge's reason: {j['reason']}"]
    return "\n".join(parts)


def to_proposal(key, answer: dict, jobs: list[dict], rule: dict | None) -> dict | None:
    if answer.get("action") == "none" or not answer.get("positions"):
        return None
    if not any(p["tier"] == "preferred" for p in answer["positions"]):
        return None
    revise = key[0] != "rule_missing" and rule is not None
    causes: dict[str, int] = defaultdict(int)
    for j in jobs:
        causes[j["cause"]] += 1
    return {
        "rule_id": rule["id"] if revise else None,
        "topic": (answer.get("topic") or (rule or {}).get("topic") or "New rule")[:200],
        "activity_type": ((rule or {}).get("activity_type") or "general")[:80],
        "guidance": answer.get("guidance", "")[:2000],
        "escalation": answer.get("escalation", "")[:1000],
        "positions": [{"tier": p["tier"], "text": p["text"][:3000], "conditions": p.get("conditions", "")[:1000]} for p in answer["positions"][:10]],
        "why": answer.get("why", "")[:600],
        "jobs": sorted({j["context_id"] for j in jobs})[:50],
        "by_person": sum(1 for j in jobs if j["by"] == "person"),
        "by_judge": sum(1 for j in jobs if j["by"] == "judge"),
        "causes": dict(causes),
    }


def proposal_text(p: dict) -> str:
    return "\n".join([p["topic"], p["guidance"], p["escalation"], p["why"], *(x["text"] + " " + x["conditions"] for x in p["positions"])])


def propose(examples: dict, judge: dict | None, root: Path, judged_dir: Path, ask) -> dict:
    version = max(int(v) for v in examples["versions"])
    rules = examples["versions"][str(version)]
    exclude = set((judge or {}).get("trained_on", []))
    g = groups(failures(examples, judged_dir, exclude), {r["id"] for r in rules})
    proposals, dropped = [], 0
    for key, jobs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        rule = next((r for r in rules if r["id"] == key[1]), None)
        answer = ask(SYSTEM, prompt_for(key, jobs, rules, root, examples.get("escalations", [])), PROPOSAL_SCHEMA)
        p = to_proposal(key, answer, jobs, rule)
        if p is None:
            continue
        if scan(proposal_text(p)):
            dropped += 1  # looks like it carries an identifier: never written
            continue
        proposals.append(p)
    return {
        "format": 1,
        "kind": "taskout-rule-proposals",
        "skill_version": SKILL_VERSION,
        "playbook_id": examples["playbook"]["id"],
        "version": version,
        "judge_prompt_sha256": (judge or {}).get("prompt_sha256"),
        "proposals": proposals[:20],
        "dropped_for_identifiers": dropped,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--examples", required=True)
    ap.add_argument("--judge", help="the approved judge.json: its verdicts count, and the jobs it was built from are left out")
    ap.add_argument("--jobs")
    ap.add_argument("--out", default="proposals.json")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    examples = load_examples(Path(a.examples))
    judge = read_json(Path(a.judge)) if a.judge else None
    out = propose(examples, judge, jobs_dir(a.jobs), JUDGED_DIR, claude_json(a.model))
    write_json(Path(a.out), out)
    print(f"Wrote {a.out}: {len(out['proposals'])} proposed changes for version {out['version']}" + (f" ({out['dropped_for_identifiers']} left out: they looked like they held an identifier)" if out["dropped_for_identifiers"] else "") + ".")
    print("Import it on the playbook's How it's working tab (Import proposed changes); a person approves each one.")


if __name__ == "__main__":
    main()
