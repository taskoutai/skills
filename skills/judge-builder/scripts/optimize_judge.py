#!/usr/bin/env python3
"""Improve the judge's instructions with GEPA until it agrees with the firm's reviewers, then write judge.json.

    pip install "gepa==0.1.4" "anthropic>=2.6"
    python scripts/optimize_judge.py [--dataset .judge-builder/dataset.json] [--out judge.json] [--budget 150]

GEPA (reflective prompt evolution) runs the judge on the training jobs, compares each answer with the person's
verdict, and has Claude read the misses, with what the person said went wrong, and rewrite the instructions. It
keeps the candidates that do best on its validation jobs. The held-out jobs are judged once, at the end, by the
best instructions: taskout recomputes the agreement on them from its own records before anyone can approve it.

Every call goes to Claude with the firm's own API key, from this machine. The instructions GEPA writes are told to
stay general (no client names, figures or quotes) and are scanned for identifiers before judge.json is written.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge_common import (  # noqa: E402
    DEFAULT_MODEL,
    JUDGE_FORMAT,
    SEED_PROMPT,
    SKILL_VERSION,
    JudgeLM,
    bucket,
    claude_judge,
    claude_reflect,
    fail,
    judge_user_message,
    normalize_judgement,
    read_json,
    scan,
    sha256,
    write_json,
)

COMPONENT = "judge_prompt"
REFLECTIVE_INPUT_LIMIT = 8_000

# GEPA's own template asks the reflection model to copy niche facts from the examples into the instruction.
# For client work that would put client details in the judge's instructions, so this one asks for general
# criteria only. It keeps GEPA's two placeholders.
SAFE_REFLECTION_TEMPLATE = """I gave a reviewer of an accounting firm's work these instructions:
```
<curr_param>
```

Below are pieces of work it reviewed against the firm's rules, its answer for each, and how the firm's own
reviewer actually received the work (the person's verdict, what went wrong, the rules at fault, and any notes).

```
<side_info>
```

Write new instructions so the reviewer's answers match the firm's reviewer. Find the patterns: what the firm's
reviewer sends back that the instructions missed, what they accept that the instructions flagged, how they tell a
rule not followed from a rule that is wrong or a rule that is missing, what they count as severe.

The instructions must be general criteria for any piece of this kind of work. Never put in a client's name, a
person's name, a figure, a date, an identifier, a reference or a quote from any piece of work.

Provide the new instructions within ``` blocks."""


def score(judged: dict, human: dict) -> float:
    """1.0 for the same outcome and the same cause; 0.7 for the same outcome only; 0 otherwise."""
    if bucket(judged["verdict"]) != bucket(human["verdict"]):
        return 0.0
    if human["verdict"] == "accepted":
        return 1.0
    same_cause = (human.get("cause") or "other") == (judged.get("cause") or "other")
    return 1.0 if same_cause else 0.7


def feedback(judged: dict, inst: dict) -> str:
    h = inst["human"]
    topics = inst.get("rule_topics", {})
    named = ", ".join(f'"{topics.get(r, r)}"' for r in h.get("defect_rule_ids") or []) or "none named"
    said = {"accepted": "accepted it as is", "accepted_with_changes": "accepted it with changes", "sent_back": "sent it back", "rejected": "rejected it"}[h["verdict"]]
    why = {"rule_broken": "a rule wasn't followed", "rule_wrong": "the rules were followed and the work was still wrong", "rule_missing": "no rule covers what went wrong", "other": "something else"}.get(h.get("cause") or "", "")
    parts = [f"The firm's reviewer {said}" + (f": {why} (rules at fault: {named})." if why else ".")]
    if h.get("severe"):
        parts.append("They marked it severe: the mistake would have reached the client.")
    if inst.get("notes"):
        parts.append(f"Their notes: {inst['notes']}")
    parts.append(f"The judge answered {judged['verdict']}" + (f" ({judged['cause']})" if judged.get("cause") else "") + f": {judged.get('reason', '')}")
    parts.append("Correct." if score(judged, h) == 1.0 else "Partly right: same outcome, different cause." if score(judged, h) > 0 else "Wrong.")
    return " ".join(parts)


def run_judge(lm: JudgeLM, prompt: str, inst: dict) -> dict:
    raw = lm(f"{prompt}\n\n{JUDGE_FORMAT}", judge_user_message(inst["rules"], inst["work"]))
    return normalize_judgement(raw, set(inst.get("rule_topics", {})))


class JudgeAdapter:
    """GEPA adapter (gepa.core.adapter.GEPAAdapter): one component, the judge's instructions."""

    # None: GEPA proposes new instructions itself, with the reflection model and SAFE_REFLECTION_TEMPLATE.
    propose_new_texts = None

    def __init__(self, lm: JudgeLM):
        self.lm = lm

    def evaluate(self, batch, candidate, capture_traces=False):
        from gepa import EvaluationBatch  # noqa: PLC0415

        outputs, scores, traces = [], [], []
        for inst in batch:
            try:
                judged = run_judge(self.lm, candidate[COMPONENT], inst)
                s = score(judged, inst["human"])
                fb = feedback(judged, inst)
            except Exception as e:  # one failed call scores 0 and says why; GEPA goes on
                judged, s, fb = {"verdict": "error", "reason": type(e).__name__}, 0.0, f"The judge call failed ({type(e).__name__})."
            outputs.append(judged)
            scores.append(s)
            traces.append({"inst": inst, "judged": judged, "feedback": fb})
        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=traces if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        records = []
        for t in eval_batch.trajectories or []:
            work = t["inst"]["work"]
            records.append({
                "Inputs": {"Rules": t["inst"]["rules"], "Work": work[:REFLECTIVE_INPUT_LIMIT] + ("\n[...]" if len(work) > REFLECTIVE_INPUT_LIMIT else "")},
                "Generated Outputs": {k: t["judged"].get(k) for k in ("verdict", "cause", "defect_rule_ids", "severe", "reason")},
                "Feedback": t["feedback"],
            })
        return {COMPONENT: records}


def held_out_answers(lm: JudgeLM, prompt: str, held: list[dict]) -> list[dict]:
    out = []
    for inst in held:
        try:
            j = run_judge(lm, prompt, inst)
        except Exception as e:
            print(f"warning: the judge call failed on a held-out job ({type(e).__name__}); counted as not answered", file=sys.stderr)
            continue
        out.append({"context_id": inst["context_id"], "verdict": j["verdict"], "cause": j["cause"], "defect_rule_ids": j["defect_rule_ids"], "severe": j["severe"]})
    return out


def agreement(answers: list[dict], held: list[dict]) -> dict:
    by = {x["context_id"]: x["human"] for x in held}
    agree = sum(1 for a in answers if bucket(a["verdict"]) == bucket(by[a["context_id"]]["verdict"]))
    failures = [a for a in answers if bucket(by[a["context_id"]]["verdict"]) == "not_accepted"]
    missed = sum(1 for a in failures if bucket(a["verdict"]) != "not_accepted")
    return {"n": len(answers), "agree": agree, "failures": len(failures), "missed_failures": missed}


def judge_file(playbook_id: str, model: str, prompt: str, trained_on: list[str], answers: list[dict], gepa_meta: dict) -> dict:
    return {
        "format": 1,
        "kind": "taskout-judge",
        "skill_version": SKILL_VERSION,
        "playbook_id": playbook_id,
        "judge_model": model,
        "prompt": prompt,
        "prompt_sha256": sha256(prompt),
        "trained_on": sorted(trained_on),
        "held_out": answers,
        "gepa": gepa_meta,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def optimize(data: dict, judge_lm: JudgeLM, reflect_lm, budget: int, seed: str = SEED_PROMPT):
    import gepa  # noqa: PLC0415

    if not data["train"] or not data["val"]:
        fail("no jobs to learn from: run build_examples.py first, and review more jobs if it says so")
    result = gepa.optimize(
        seed_candidate={COMPONENT: seed},
        trainset=data["train"],
        valset=data["val"],
        adapter=JudgeAdapter(judge_lm),
        reflection_lm=reflect_lm,
        reflection_prompt_template=SAFE_REFLECTION_TEMPLATE,
        max_metric_calls=budget,
        reflection_minibatch_size=3,
        seed=0,
        display_progress_bar=False,
    )
    best = result.best_candidate
    prompt = best[COMPONENT] if isinstance(best, dict) else str(best)
    meta = {"version": getattr(gepa, "__version__", "0.1.4"), "max_metric_calls": budget, "candidates": len(result.candidates), "val_score": round(float(result.val_aggregate_scores[result.best_idx]), 3)}
    return prompt, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", default=".judge-builder/dataset.json")
    ap.add_argument("--out", default="judge.json")
    ap.add_argument("--budget", type=int, default=150, help="judge calls GEPA may make (each is one Claude call)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="the judge's model")
    ap.add_argument("--reflection-model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    data = read_json(Path(a.dataset))
    judge_lm = claude_judge(a.model)
    prompt, meta = optimize(data, judge_lm, claude_reflect(a.reflection_model), a.budget)
    codes = scan(prompt)
    if codes:
        fail(f"the judge's instructions contain what looks like an identifier ({', '.join(codes)}); nothing written. Run again, or edit the seed.")
    answers = held_out_answers(judge_lm, prompt, data["held_out"])
    trained = [x["context_id"] for x in data["train"] + data["val"]]
    write_json(Path(a.out), judge_file(data["playbook_id"], a.model, prompt, trained, answers, meta))
    s = agreement(answers, data["held_out"])
    print(f"Wrote {a.out}. On {s['n']} held-out jobs the judge agrees with people on {s['agree']}; it missed {s['missed_failures']} of {s['failures']} sent back or rejected.")
    print("Import it on the playbook's How it's working tab (Import a judge). taskout checks these numbers against its own records.")


if __name__ == "__main__":
    main()
