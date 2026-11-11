#!/usr/bin/env python3
"""Join taskout's verdicts with the work the agents kept on this machine, and split them.

    python scripts/build_examples.py --examples taskout-examples.json [--jobs taskout-jobs] [--out .judge-builder]

Only jobs taskout picked at random for review are used: the flagged ones are skewed towards failures (the same
reason they never count in the playbook's headline). A fixed third of them, by a hash of the job, is held out:
GEPA never sees it, and taskout checks the judge's answers on it against people's verdicts before anyone can
approve the judge. Writes <out>/dataset.json. Nothing leaves this machine.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge_common import held_out, in_val, is_failure, jobs_dir, load_examples, load_job, render_rules, write_json  # noqa: E402

MIN_HELD_OUT = 10
MIN_HELD_OUT_FAILURES = 2
MIN_TRAIN = 10


def build(examples: dict, root: Path) -> dict:
    versions = {int(v): rules for v, rules in examples.get("versions", {}).items()}
    out = {"playbook_id": examples["playbook"]["id"], "train": [], "val": [], "held_out": [], "skipped": {"not_sampled": 0, "no_local_work": 0, "unknown_version": 0}}
    for v in examples.get("verdicts", []):
        if v.get("picked") != "random":
            out["skipped"]["not_sampled"] += 1
            continue
        rules = versions.get(v.get("version"))
        if rules is None:
            out["skipped"]["unknown_version"] += 1
            continue
        job = load_job(root, v["context_id"])
        if job is None:
            out["skipped"]["no_local_work"] += 1
            continue
        inst = {
            "context_id": v["context_id"],
            "version": v["version"],
            "rules": render_rules(rules),
            "rule_topics": {r["id"]: r["topic"] for r in rules},
            "work": job["work"],
            "notes": job["notes"],
            "human": {k: v.get(k) for k in ("verdict", "cause", "defect_rule_ids", "severe")},
        }
        side = "held_out" if held_out(v["context_id"]) else "val" if in_val(v["context_id"]) else "train"
        out[side].append(inst)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--examples", required=True, help="the examples file downloaded from taskout")
    ap.add_argument("--jobs", help="the jobs folder (default: $TASKOUT_JOBS_DIR, else taskout-jobs)")
    ap.add_argument("--out", default=".judge-builder")
    a = ap.parse_args()
    data = build(load_examples(Path(a.examples)), jobs_dir(a.jobs))
    write_json(Path(a.out) / "dataset.json", data)
    ho = data["held_out"]
    failures = sum(1 for x in ho if is_failure(x["human"]["verdict"]))
    print(f"train {len(data['train'])}, GEPA validation {len(data['val'])}, held out {len(ho)} ({failures} sent back or rejected)")
    print(f"skipped: {data['skipped']['not_sampled']} not picked at random, {data['skipped']['no_local_work']} without work on this machine, {data['skipped']['unknown_version']} on an unknown version")
    short = []
    if len(data["train"]) + len(data["val"]) < MIN_TRAIN:
        short.append(f"at least {MIN_TRAIN} jobs to learn from")
    if len(ho) < MIN_HELD_OUT:
        short.append(f"at least {MIN_HELD_OUT} held-out jobs")
    if failures < MIN_HELD_OUT_FAILURES:
        short.append(f"at least {MIN_HELD_OUT_FAILURES} held-out jobs that were sent back or rejected")
    if short:
        print("Not enough yet for a judge taskout will approve: it needs " + "; ".join(short) + ". Keep reviewing jobs, then run this again.")


if __name__ == "__main__":
    main()
