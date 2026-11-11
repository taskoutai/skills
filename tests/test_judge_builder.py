"""Tests for the judge-builder skill's scripts (skills/judge-builder/scripts/).

Real scripts, real files in a temp dir, fictional data only. Claude is replaced by plain functions: no network,
no key. The GEPA run test uses the real gepa package with those stand-ins and is skipped when gepa isn't
installed (pip install "gepa==0.1.4"); everything else runs without it.
"""
import importlib.util
import json
import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "skills" / "judge-builder" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


common = load("judge_common")
build_examples = load("build_examples")
optimize_judge = load("optimize_judge")
judge_jobs = load("judge_jobs")
propose_rules = load("propose_rules")

PB = "pb_" + "a" * 32
R1 = "pbr_" + "1" * 32
R2 = "pbr_" + "2" * 32
RULES = [
    {"id": R1, "topic": "Home office deduction", "activity_type": "deductions", "guidance": "", "escalation": "Ask the reviewer when the space is shared.",
     "positions": [{"id": "pbp_" + "1" * 32, "tier": "preferred", "text": "Use the simplified method.", "conditions": ""}, {"id": "pbp_" + "2" * 32, "tier": "unacceptable", "text": "Deduct a shared space.", "conditions": ""}]},
    {"id": R2, "topic": "Estimated payments", "activity_type": "payments", "guidance": "", "escalation": "",
     "positions": [{"id": "pbp_" + "3" * 32, "tier": "preferred", "text": "Use the safe harbor.", "conditions": ""}]},
]


def ctx(i):
    return "ctx_" + format(i, "032x")


def examples(verdicts, escalations=()):
    return {"format": 1, "kind": "taskout-judge-examples", "playbook": {"id": PB, "title": "Returns"}, "versions": {"2": RULES}, "verdicts": verdicts, "escalations": list(escalations)}


def save_job(root, c, work, notes=None, version=2):
    d = root / c
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"context_id": c, "playbook_id": PB, "version": version}))
    (d / "work.md").write_text(work)
    if notes:
        (d / "review.md").write_text(notes)


def verdict(c, v, cause=None, rules=(), picked="random", severe=False):
    return {"context_id": c, "version": 2, "picked": picked, "verdict": v, "cause": cause, "defect_rule_ids": list(rules), "severe": severe}


# ------------------------------------------------------------------------------------------- build_examples
def test_build_uses_sampled_jobs_with_local_work_and_a_fixed_split(tmp_path):
    vs = [verdict(ctx(i), "accepted") for i in range(60)] + [verdict(ctx(100), "sent_back", "rule_broken", [R1], picked="flagged"), verdict(ctx(101), "accepted")]
    for i in range(60):
        save_job(tmp_path, ctx(i), f"Work {i}: used the simplified method.")
    data = build_examples.build(examples(vs), tmp_path)
    assert data["skipped"] == {"not_sampled": 1, "no_local_work": 1, "unknown_version": 0}
    ids = {s: {x["context_id"] for x in data[s]} for s in ("train", "val", "held_out")}
    assert sum(len(v) for v in ids.values()) == 60
    assert not (ids["held_out"] & (ids["train"] | ids["val"]))
    # The split is by a hash of the job: the same every run, about a third held out.
    assert ids["held_out"] == {c for c in (ctx(i) for i in range(60)) if common.held_out(c)}
    assert 10 <= len(ids["held_out"]) <= 30
    x = next(iter(data["train"]))
    assert x["rule_topics"] == {R1: "Home office deduction", R2: "Estimated payments"}
    assert "Use the simplified method." in x["rules"] and R1 in x["rules"]


def test_load_job_ignores_names_that_are_not_job_ids(tmp_path):
    (tmp_path / "../escape").resolve()
    assert common.load_job(tmp_path, "../etc") is None
    assert common.load_job(tmp_path, ctx(1)) is None


# ------------------------------------------------------------------------------------------- scoring
def test_score_and_feedback():
    h = {"verdict": "sent_back", "cause": "rule_wrong", "defect_rule_ids": [R1], "severe": True}
    inst = {"human": h, "rule_topics": {R1: "Home office deduction"}, "notes": "The method doesn't fit a part-year office."}
    assert optimize_judge.score({"verdict": "rejected", "cause": "rule_wrong"}, h) == 1.0
    assert optimize_judge.score({"verdict": "sent_back", "cause": "rule_broken"}, h) == 0.7
    assert optimize_judge.score({"verdict": "accepted", "cause": None}, h) == 0.0
    assert optimize_judge.score({"verdict": "accepted", "cause": None}, {"verdict": "accepted"}) == 1.0
    assert optimize_judge.score({"verdict": "accepted_with_changes", "cause": "other"}, {"verdict": "accepted"}) == 0.0
    fb = optimize_judge.feedback({"verdict": "accepted", "cause": None, "reason": "Looks fine."}, inst)
    assert "sent it back" in fb and '"Home office deduction"' in fb and "severe" in fb and "part-year office" in fb and fb.endswith("Wrong.")


def test_normalize_keeps_only_known_rules_and_consistent_causes():
    rule_ids = {R1}
    assert common.normalize_judgement({"verdict": "accepted", "cause": "rule_wrong", "defect_rule_ids": [R1]}, rule_ids)["cause"] is None
    assert common.normalize_judgement({"verdict": "sent_back", "cause": "none", "defect_rule_ids": []}, rule_ids)["cause"] == "other"
    n = common.normalize_judgement({"verdict": "sent_back", "cause": "rule_broken", "defect_rule_ids": ["pbr_" + "9" * 32]}, rule_ids)
    assert n["cause"] == "other" and n["defect_rule_ids"] == []
    assert common.normalize_judgement({"verdict": "weird"}, rule_ids)["verdict"] == "sent_back"


def test_agreement_counts_missed_failures():
    held = [{"context_id": ctx(i), "human": {"verdict": v}} for i, v in enumerate(["accepted", "sent_back", "rejected", "accepted_with_changes"])]
    answers = [{"context_id": ctx(0), "verdict": "accepted"}, {"context_id": ctx(1), "verdict": "accepted"}, {"context_id": ctx(2), "verdict": "sent_back"}, {"context_id": ctx(3), "verdict": "accepted"}]
    assert optimize_judge.agreement(answers, held) == {"n": 4, "agree": 2, "failures": 2, "missed_failures": 1}


def test_scan_finds_identifier_shapes():
    assert common.scan("Use the simplified method for any home office.") == []
    assert "NON_FICTIONAL_SSN" in common.scan("client 123-45-6789")
    assert "NON_FICTIONAL_EMAIL" in common.scan("ask jane@firm.com")
    assert common.scan("ask someone@example.com") == []
    assert "UNEXPLAINED_LONG_NUMBER" in common.scan("account 123456789012")
    assert common.scan("over 1,000,000 in receipts") == []


# ------------------------------------------------------------------------------------------- GEPA
def fake_judge(strict):
    """A stand-in judge: with 'shared space' in its instructions it sends back work that deducts one."""
    def call(system, user):
        bad = "shared space" in user.split("# The finished work", 1)[1]
        if strict in system and bad:
            return {"verdict": "sent_back", "cause": "rule_broken", "defect_rule_ids": [R1], "severe": False, "reason": "Deducted a shared space."}
        return {"verdict": "accepted", "cause": "none", "defect_rule_ids": [], "severe": False, "reason": "Fine."}
    return call


def test_adapter_scores_and_builds_reflective_records():
    gepa = pytest.importorskip("gepa")
    adapter = optimize_judge.JudgeAdapter(fake_judge("CHECK SHARED"))
    batch = [
        {"context_id": ctx(1), "rules": "r", "rule_topics": {R1: "Home office deduction"}, "work": "Deducted a shared space.", "notes": "", "human": {"verdict": "sent_back", "cause": "rule_broken", "defect_rule_ids": [R1], "severe": False}},
        {"context_id": ctx(2), "rules": "r", "rule_topics": {R1: "Home office deduction"}, "work": "Simplified method.", "notes": "", "human": {"verdict": "accepted", "cause": None, "defect_rule_ids": [], "severe": False}},
    ]
    ev = adapter.evaluate(batch, {"judge_prompt": "Be kind."}, capture_traces=True)
    assert isinstance(ev, gepa.EvaluationBatch) and ev.scores == [0.0, 1.0]
    recs = adapter.make_reflective_dataset({"judge_prompt": "Be kind."}, ev, ["judge_prompt"])["judge_prompt"]
    assert recs[0]["Generated Outputs"]["verdict"] == "accepted" and "sent it back" in recs[0]["Feedback"]
    assert adapter.evaluate(batch, {"judge_prompt": "CHECK SHARED"}).scores == [1.0, 1.0]

    def broken(system, user):
        raise RuntimeError("network")
    ev = optimize_judge.JudgeAdapter(broken).evaluate(batch[:1], {"judge_prompt": "x"}, capture_traces=True)
    assert ev.scores == [0.0] and "failed" in ev.trajectories[0]["feedback"]


def test_gepa_run_finds_instructions_that_agree_with_people(tmp_path):
    pytest.importorskip("gepa")
    vs = []
    for i in range(40):
        bad = i % 3 == 0
        save_job(tmp_path, ctx(i), "Deducted a shared space." if bad else "Used the simplified method.")
        vs.append(verdict(ctx(i), "sent_back", "rule_broken", [R1]) if bad else verdict(ctx(i), "accepted"))
    data = build_examples.build(examples(vs), tmp_path)
    reflections = []

    def reflect(prompt):
        reflections.append(prompt)
        return "```\nCHECK SHARED spaces against the home office rule.\n```"

    prompt, meta = optimize_judge.optimize(data, fake_judge("CHECK SHARED"), reflect, budget=60)
    assert "CHECK SHARED" in prompt and meta["candidates"] >= 2 and meta["val_score"] == 1.0
    # The reflection prompt is ours: general criteria only, never GEPA's "include niche facts".
    assert reflections and "Never put in a client's name" in reflections[0] and "niche" not in reflections[0]
    answers = optimize_judge.held_out_answers(fake_judge("CHECK SHARED"), prompt, data["held_out"])
    s = optimize_judge.agreement(answers, data["held_out"])
    assert s["n"] == len(data["held_out"]) and s["agree"] == s["n"] and s["missed_failures"] == 0
    f = optimize_judge.judge_file(PB, "claude-opus-5-5", prompt, [x["context_id"] for x in data["train"] + data["val"]], answers, meta)
    assert f["kind"] == "taskout-judge" and f["prompt_sha256"] == common.sha256(prompt)
    assert not set(f["trained_on"]) & {a["context_id"] for a in f["held_out"]}


# ------------------------------------------------------------------------------------------- judge_jobs
def test_judge_jobs_skips_jobs_the_judge_was_built_from(tmp_path):
    for i in range(4):
        save_job(tmp_path, ctx(i), "Deducted a shared space.")
    save_job(tmp_path, ctx(9), "x", version=7)  # a version the examples file doesn't have
    judge = {"playbook_id": PB, "trained_on": [ctx(0)], "held_out": [{"context_id": ctx(1)}], "prompt": "CHECK SHARED"}
    judged = tmp_path / "judged"
    judged.mkdir()
    (judged / f"{ctx(2)}.json").write_text("{}")
    todo = judge_jobs.pending(judge, examples([]), tmp_path, judged)
    assert [t["context_id"] for t in todo] == [ctx(3)]
    j = optimize_judge.run_judge(fake_judge("CHECK SHARED"), judge["prompt"], todo[0])
    assert j["verdict"] == "sent_back" and j["defect_rule_ids"] == [R1]


# ------------------------------------------------------------------------------------------- propose_rules
def test_propose_groups_failures_and_leaves_out_judge_training_jobs(tmp_path):
    vs = [verdict(ctx(i), "sent_back", "rule_wrong", [R1]) for i in range(3)] + [verdict(ctx(10), "sent_back", "rule_missing")] + [verdict(ctx(20), "accepted")]
    for i in (0, 1, 2, 10):
        save_job(tmp_path, ctx(i), "Used the simplified method for a part-year office.", notes="Part-year offices need actual expenses.")
    judged = tmp_path / ".judged"
    judged.mkdir()
    # The approved judge's verdict on a job no person reviewed counts too.
    (judged / f"{ctx(11)}.json").write_text(json.dumps({"context_id": ctx(11), "verdict": "sent_back", "cause": "rule_missing", "defect_rule_ids": [], "severe": False, "reason": "No rule on vehicle logs."}))
    asks = []

    def ask(system, prompt, schema):
        asks.append(prompt)
        if "followed this rule and was still wrong" in prompt:
            return {"action": "revise", "topic": "Home office deduction", "guidance": "", "escalation": "Ask the reviewer when the space is shared.", "positions": [{"tier": "preferred", "text": "Use the simplified method for a full-year office.", "conditions": ""}, {"tier": "fallback", "text": "Use actual expenses.", "conditions": "The office was used for part of the year."}], "why": "Part-year offices were sent back."}
        return {"action": "new", "topic": "Vehicle logs", "guidance": "", "escalation": "", "positions": [{"tier": "preferred", "text": "Keep a mileage log, call 555-012-3456.", "conditions": ""}], "why": "x"}

    out = propose_rules.propose(examples(vs, [{"rule_id": R1, "question": "Part-year office?", "answer": "Use actual expenses."}]), {"trained_on": [ctx(0)]}, tmp_path, judged, ask)
    assert out["kind"] == "taskout-rule-proposals" and out["version"] == 2
    # ctx(0) was used to build the judge: left out, so 2 jobs remain for the rule (still a group).
    [p] = out["proposals"]
    assert p["rule_id"] == R1 and p["jobs"] == [ctx(1), ctx(2)] and p["by_person"] == 2 and p["causes"] == {"rule_wrong": 2}
    assert p["positions"][1]["conditions"] == "The office was used for part of the year."
    assert "Part-year offices need actual expenses." in asks[0] and "Use actual expenses." in asks[0]
    # The missing-rule proposal held a phone number: never written.
    assert out["dropped_for_identifiers"] == 1


def test_propose_needs_two_jobs_and_a_preferred_position(tmp_path):
    vs = [verdict(ctx(1), "sent_back", "rule_broken", [R2])]
    out = propose_rules.propose(examples(vs), None, tmp_path, tmp_path / "none", lambda *a: pytest.fail("no call expected"))
    assert out["proposals"] == []
    key = ("rule_broken", R2)
    assert propose_rules.to_proposal(key, {"action": "revise", "positions": [{"tier": "fallback", "text": "x", "conditions": ""}]}, [], RULES[1]) is None
    assert propose_rules.to_proposal(key, {"action": "none", "positions": []}, [], RULES[1]) is None
