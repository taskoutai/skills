#!/usr/bin/env python3
"""Score the arms and write the report.

    python scripts/report.py [--out playbook-eval]

Writes <out>/report.md (for the person) and <out>/result.json (counts, rule topics, skill names and hashes: no
engagement names, no work, no figures; scanned for identifiers and refused on a hit).

Correct application, per engagement: of the rules the team's work touched (the confirmed reading), the share where
the arm took the same position. Arms are compared with the baseline on the same engagements (paired), with a 95%
interval. Closer to the team: how often the judge preferred the arm's work to the baseline's, both orders agreeing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_common import SKILL_VERSION, STATE, fail, load_rubric, load_setup, mean_ci, red_lines, scan, sha256, wilson, write_json  # noqa: E402

MIN_CASES = 5  # below this many paired engagements, no "better" or "worse"


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def collect(setup: dict, state: Path) -> dict:
    cases = {}
    for case in setup["cases"]:
        jd = state / "judged" / f"case-{case['n']}"
        ref = load(jd / "reference.json")
        if not ref:
            continue
        arms = {}
        for a in setup["arms"]:
            meta = load(state / "runs" / f"case-{case['n']}" / a["name"] / "meta.json")
            arms[a["name"]] = {"meta": meta, "reading": load(jd / f"{a['name']}.json"), "pair": load(jd / f"pair-{a['name']}.json")}
        cases[case["n"]] = {"ref": ref, "arms": arms}
    return cases


def case_accuracy(ref: list[dict], got: list[dict]) -> tuple[float | None, list[tuple[int, bool]]]:
    per_rule = []
    for r, g in zip(ref, got):
        if r["touched"]:
            per_rule.append((r["rule"], g["touched"] and g["position"] == r["position"]))
    if not per_rule:
        return None, []
    return sum(ok for _, ok in per_rule) / len(per_rule), per_rule


def verdict_words(ci: dict) -> str:
    if ci["n"] < MIN_CASES or ci["low"] is None:
        return f"too few engagements to tell (needs {MIN_CASES} judged in both arms)"
    if ci["low"] > 0:
        return "better"
    if ci["high"] < 0:
        return "worse"
    return "about the same"


def score(setup: dict, rules: list[dict], cases: dict) -> dict:
    base = setup["baseline"]
    lines = red_lines(rules)
    arms_out, per_rule = [], {a["name"]: {} for a in setup["arms"]}
    acc = {a["name"]: {} for a in setup["arms"]}
    for a in setup["arms"]:
        name, metas, red, asked = a["name"], [], 0, [0, 0]
        for n, c in cases.items():
            x = c["arms"][name]
            if x["meta"]:
                metas.append(x["meta"])
            if not x["reading"]:
                continue
            got = x["reading"]["rules"]
            value, rule_hits = case_accuracy(c["ref"]["rules"], got)
            if value is not None:
                acc[name][n] = value
            for rule, ok in rule_hits:
                per_rule[name].setdefault(rule, []).append(ok)
            red += sum(1 for g in got if g["touched"] and (g["rule"], g["position"]) in lines)
            for r, g in zip(c["ref"]["rules"], got):
                if r["touched"] and r["asked_person"]:
                    asked[1] += 1
                    asked[0] += int(g["asked_person"])
        ok_runs = [m for m in metas if m.get("ok")]
        mean = lambda k: (sum(m.get(k) or 0 for m in ok_runs) / len(ok_runs)) if ok_runs else None  # noqa: E731
        playbook_loaded = sum(1 for m in ok_runs if a["playbook"] and a["playbook"]["name"] in " ".join(m.get("skills_used") or []))
        arms_out.append({
            "name": name,
            "skills": [{"name": s["name"], "sha256": s["sha256"]} for s in a["skills"]],
            "playbook": {"name": a["playbook"]["name"], "rules_sha256": a["playbook"]["rules_sha256"]} if a["playbook"] else None,
            "runs": len(metas),
            "runs_ok": len(ok_runs),
            "playbook_skill_used": playbook_loaded if a["playbook"] else None,
            "correct_application": mean_ci(list(acc[name].values())),
            "red_lines_taken": red,
            "asked_where_team_asked": {"asked": asked[0], "of": asked[1]},
            "mean_cost_usd": mean("cost_usd"),
            "mean_turns": mean("turns"),
            "mean_seconds": mean("seconds"),
        })
    comparisons = []
    for a in setup["arms"]:
        name = a["name"]
        if name == base:
            continue
        paired = [acc[name][n] - acc[base][n] for n in acc[name] if n in acc[base]]
        diff = mean_ci(paired)
        wins = losses = ties = 0
        for c in cases.values():
            p = c["arms"][name]["pair"]
            if not p:
                continue
            wins += p["winner"] == name
            losses += p["winner"] == base
            ties += p["winner"] == "tie"
        comparisons.append({
            "arm": name,
            "baseline": base,
            "correct_application_difference": diff,
            "verdict": verdict_words(diff),
            "closer_to_team": {"wins": wins, "losses": losses, "ties": ties, "win_rate_of_decided": wilson(wins, wins + losses)},
        })
    rule_rows = []
    for i, r in enumerate(rules):
        row = {"rule": i, "topic": r["topic"], "arms": {}}
        for a in setup["arms"]:
            hits = per_rule[a["name"]].get(i, [])
            row["arms"][a["name"]] = {"right": sum(hits), "of": len(hits)}
        rule_rows.append(row)
    return {"arms": arms_out, "comparisons": comparisons, "rules": rule_rows}


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{round(100 * x)}%"


def markdown(setup: dict, scored: dict, cases: dict, confirmed: int) -> str:
    out = ["# Playbook eval", "", f"Task given to every arm: {setup['task']}", "",
           f"{len(cases)} engagements judged ({confirmed} with readings confirmed by a person), {len(setup['arms'])} arms. Baseline: {setup['baseline']}.", ""]
    if confirmed < len(cases):
        out += ["**Some readings of what the team did were not confirmed by a person: treat those results as provisional.**", ""]
    out += ["## Arms", "", "| Arm | Runs ok | Correct application (95% interval) | Red lines taken | Asked where the team asked | Playbook skill used | Avg cost | Avg turns |", "|---|---|---|---|---|---|---|---|"]
    for a in scored["arms"]:
        ca = a["correct_application"]
        interval = f"{pct(ca['mean'])} ({pct(ca['low'])} to {pct(ca['high'])})" if ca["low"] is not None else pct(ca["mean"])
        used = "n/a" if a["playbook_skill_used"] is None else f"{a['playbook_skill_used']} of {a['runs_ok']}"
        cost = "n/a" if a["mean_cost_usd"] is None else f"${a['mean_cost_usd']:.2f}"
        turns = "n/a" if a["mean_turns"] is None else f"{a['mean_turns']:.0f}"
        out.append(f"| {a['name']} | {a['runs_ok']} of {a['runs']} | {interval} | {a['red_lines_taken']} | {a['asked_where_team_asked']['asked']} of {a['asked_where_team_asked']['of']} | {used} | {cost} | {turns} |")
    out += ["", "## Against the baseline", ""]
    for c in scored["comparisons"]:
        d, w = c["correct_application_difference"], c["closer_to_team"]
        diff = "n/a" if d["mean"] is None else f"{d['mean'] * 100:+.0f} points" + (f" (95% interval {d['low'] * 100:+.0f} to {d['high'] * 100:+.0f})" if d["low"] is not None else "")
        out += [f"**{c['arm']}**: {c['verdict']}. Correct application {diff} over {d['n']} paired engagements.",
                f"Closer to what the team sent: {w['wins']} engagements, baseline closer: {w['losses']}, no clear difference: {w['ties']}.", ""]
    names = [a["name"] for a in scored["arms"]]
    out += ["## Rule by rule", "", "Right / engagements that touched the rule.", "", "| Rule | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for r in scored["rules"]:
        cells = [f"{r['arms'][n]['right']} / {r['arms'][n]['of']}" if r["arms"][n]["of"] else "-" for n in names]
        out.append(f"| {r['topic']} | " + " | ".join(cells) + " |")
    out += ["", "A rule the playbook arm gets wrong more often than the skills-only arm is a rule to look at first: its",
            "wording, its conditions, or a fallback that should be the preferred position.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="playbook-eval")
    ap.add_argument("--state", default=str(STATE))
    a = ap.parse_args(argv)
    state, out = Path(a.state), Path(a.out)
    setup = load_setup(state)
    rubric = load_rubric(Path(setup["rubric"]))
    if sha256(Path(setup["rubric"]).read_text(encoding="utf-8")) != setup["rubric_sha256"]:
        fail("the rubric changed since setup_eval.py: the readings no longer match its rules")
    cases = collect(setup, state)
    if not cases:
        fail("nothing judged yet: run judge_runs.py --stage reference, then --stage arms")
    confirmed = sum(1 for c in cases.values() if c["ref"].get("confirmed"))
    scored = score(setup, rubric["rules"], cases)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(markdown(setup, scored, cases, confirmed), encoding="utf-8")
    result = {
        "kind": "taskout-playbook-eval-result",
        "format": 1,
        "skill_version": SKILL_VERSION,
        "task_sha256": setup["task_sha256"],
        "rubric_rules_sha256": (rubric.get("local_test") or {}).get("content_sha256"),
        "model": setup["model"],
        "engagements": len(cases),
        "readings_confirmed": confirmed,
        "baseline": setup["baseline"],
        **scored,
    }
    hits = scan(json.dumps(result, ensure_ascii=False))
    if hits:
        fail(f"result.json would hold identifier-like text ({', '.join(hits)}): check the rule topics and skill names; report.md is written")
    write_json(out / "result.json", result)
    print(f"Wrote {out / 'report.md'} and {out / 'result.json'}.")
    for c in scored["comparisons"]:
        print(f"{c['arm']} vs {c['baseline']}: {c['verdict']}")
    return result


if __name__ == "__main__":
    main()
