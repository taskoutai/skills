#!/usr/bin/env python3
"""Judge finished jobs with the firm's approved judge, here, and write the verdicts for taskout.

    python scripts/judge_jobs.py --judge judge.json --examples taskout-examples.json [--jobs taskout-jobs] [--out judge-verdicts.json]

Judges every job of the judge's playbook saved in the jobs folder that it hasn't judged yet, except the jobs it was
built from or measured on. Writes judge-verdicts.json (ids, verdicts, causes, rule ids: upload it on the playbook's
How it's working tab) and keeps each verdict with its reason in .judge-builder/judged/ on this machine, for
propose_rules.py. Download a fresh examples file first so the rules of new versions are there.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge_common import (  # noqa: E402
    claude_judge,
    fail,
    jobs_dir,
    load_examples,
    load_job,
    read_json,
    render_rules,
    sha256,
    write_json,
)
from optimize_judge import run_judge  # noqa: E402

JUDGED_DIR = Path(".judge-builder/judged")


def pending(judge: dict, examples: dict, root: Path, judged_dir: Path) -> list[dict]:
    versions = {int(v): rules for v, rules in examples.get("versions", {}).items()}
    skip = set(judge.get("trained_on", [])) | {x["context_id"] for x in judge.get("held_out", [])}
    out = []
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        ctx = d.name
        if ctx in skip or (judged_dir / f"{ctx}.json").exists():
            continue
        job = load_job(root, ctx)
        if not job or job["meta"].get("playbook_id") != judge["playbook_id"]:
            continue
        rules = versions.get(job["meta"].get("version"))
        if rules is None:
            continue
        out.append({"context_id": ctx, "version": job["meta"]["version"], "rules": render_rules(rules), "rule_topics": {r["id"]: r["topic"] for r in rules}, "work": job["work"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--judge", default="judge.json")
    ap.add_argument("--examples", required=True)
    ap.add_argument("--jobs")
    ap.add_argument("--out", default="judge-verdicts.json")
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    judge = read_json(Path(a.judge))
    if judge.get("kind") != "taskout-judge":
        fail(f"{a.judge} is not a judge file")
    examples = load_examples(Path(a.examples))
    if examples["playbook"]["id"] != judge["playbook_id"]:
        fail("the examples file is for another playbook")
    todo = pending(judge, examples, jobs_dir(a.jobs), JUDGED_DIR)[: a.limit]
    lm = claude_judge(judge.get("judge_model") or "claude-opus-5-5")
    verdicts = []
    for inst in todo:
        try:
            j = run_judge(lm, judge["prompt"], inst)
        except Exception as e:
            print(f"warning: skipped {inst['context_id']} ({type(e).__name__})", file=sys.stderr)
            continue
        write_json(JUDGED_DIR / f"{inst['context_id']}.json", {"context_id": inst["context_id"], "version": inst["version"], **j})
        verdicts.append({"context_id": inst["context_id"], "verdict": j["verdict"], "cause": j["cause"], "defect_rule_ids": j["defect_rule_ids"], "severe": j["severe"]})
    write_json(Path(a.out), {"format": 1, "kind": "taskout-judge-verdicts", "playbook_id": judge["playbook_id"], "prompt_sha256": sha256(judge["prompt"]), "verdicts": verdicts})
    print(f"Judged {len(verdicts)} jobs. Upload {a.out} on the playbook's How it's working tab (Upload judge verdicts).")


if __name__ == "__main__":
    main()
