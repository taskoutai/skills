#!/usr/bin/env python3
"""Set up an eval: which engagements, which arms (skills only, skills + playbook, optionally a second version).

    python scripts/setup_eval.py --cases kept-back/ --skills ~/.claude/skills/return-prep \\
        --playbook playbook-export/individual-return-preparation --rubric playbook.json \\
        --task "Prepare the workpapers for this engagement." [--playbook-b v4-export/<name>] [--no-skills-only]

--cases is a folder with one subfolder per engagement, each with documents/ (what came in) and deliverables/ (what
the team produced). Use engagements the playbook was NOT built from (the ones kept back). --skills is a skill folder
or a folder of skill folders (the firm's own skills; repeat it for several). --playbook is the playbook's skill
folder (playbook-export/<name>/ from the playbook-builder, or a version's agent export from taskout). --rubric is the
playbook.json whose rules the judge measures every arm by. Writes .playbook-eval/eval.json and prints the budget.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_common import DEFAULT_MODEL, STATE, describe_skill, fail, load_rubric, sha256, skill_folders, write_json  # noqa: E402


def find_cases(root: Path) -> list[Path]:
    if not root.is_dir():
        fail(f"{root} is not a folder")
    cases = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    bad = [p.name for p in cases if not (p / "documents").is_dir() or not (p / "deliverables").is_dir()]
    if bad:
        fail(f"{len(bad)} engagement folder(s) lack documents/ or deliverables/ (e.g. {bad[0]}): each needs both")
    if not cases:
        fail(f"no engagement folders in {root}")
    return cases


def firm_skills(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        for folder in skill_folders(Path(p).expanduser()):
            s = describe_skill(folder)
            if s["rules_sha256"]:
                fail(f"{folder} is a playbook export (it has rules-sha256): pass it with --playbook, not --skills")
            out.append(s)
    names = [s["name"] for s in out]
    if len(set(names)) != len(names):
        fail("two firm skills have the same name")
    return out


def playbook_skill(path: str) -> dict:
    folders = skill_folders(Path(path).expanduser())
    if len(folders) != 1:
        fail(f"{path}: pass the one playbook skill folder (playbook-export/<name>/), not a folder of several")
    s = describe_skill(folders[0])
    if not s["rules_sha256"]:
        fail(f"{path} has no rules-sha256 in its frontmatter: it isn't a playbook export")
    return s


def budget(n_cases: int, n_arms: int) -> dict:
    agent_runs = n_cases * n_arms
    judge_calls = n_cases + n_cases * n_arms + 2 * n_cases * (n_arms - 1)  # reference reading, one per arm, both orders per pair
    return {"agent_runs": agent_runs, "judge_calls": judge_calls}


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--skills", action="append", default=[])
    ap.add_argument("--playbook", required=True)
    ap.add_argument("--playbook-b")
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--task", required=True, help="what each agent is asked to do, the same in every arm")
    ap.add_argument("--no-skills-only", action="store_true", help="leave out the skills-only arm (compare two playbook versions only)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--allow-bash", action="store_true", help="let the agent run commands (the firm's skills may need scripts)")
    ap.add_argument("--state", default=str(STATE))
    a = ap.parse_args(argv)

    rubric_path = Path(a.rubric).resolve()
    rubric = load_rubric(rubric_path)
    cases = find_cases(Path(a.cases))
    skills = firm_skills(a.skills)
    pb = playbook_skill(a.playbook)
    arms = []
    if not a.no_skills_only:
        if not skills:
            fail("the skills-only arm needs at least one --skills (or pass --no-skills-only)")
        arms.append({"name": "skills-only", "skills": skills, "playbook": None})
    arms.append({"name": "skills+playbook", "skills": skills, "playbook": pb})
    if a.playbook_b:
        pb_b = playbook_skill(a.playbook_b)
        if pb_b["rules_sha256"] == pb["rules_sha256"]:
            fail("--playbook and --playbook-b have the same rules")
        arms.append({"name": "skills+playbook-b", "skills": skills, "playbook": pb_b})
    if len(arms) < 2:
        fail("an eval needs two arms: add --playbook-b, or keep the skills-only arm")

    fp = (rubric.get("local_test") or {}).get("content_sha256")
    if fp and fp not in {arm["playbook"]["rules_sha256"] for arm in arms if arm["playbook"]}:
        print("note: the rubric's rules differ from every playbook arm's; the judge measures all arms by the rubric's rules.", file=sys.stderr)

    setup = {
        "kind": "taskout-playbook-eval-setup",
        "format": 1,
        "task": a.task,
        "task_sha256": sha256(a.task),
        "rubric": str(rubric_path),
        "rubric_sha256": sha256(rubric_path.read_text(encoding="utf-8")),
        "cases": [{"n": i + 1, "path": str(p.resolve())} for i, p in enumerate(cases)],
        "arms": arms,
        "baseline": arms[0]["name"],
        "model": a.model,
        "max_turns": a.max_turns,
        "allow_bash": a.allow_bash,
    }
    write_json(Path(a.state) / "eval.json", setup)
    b = budget(len(cases), len(arms))
    print(f"{len(cases)} engagements x {len(arms)} arms ({', '.join(x['name'] for x in arms)}).")
    print(f"Budget: {b['agent_runs']} Claude Code runs (up to {a.max_turns} turns each) and {b['judge_calls']} judge calls, on the firm's key.")
    print("Use only engagements the playbook was not built from. Confirm the budget with the person before run_arms.py.")
    return setup


if __name__ == "__main__":
    main()
