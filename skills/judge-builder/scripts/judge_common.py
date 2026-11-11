"""Shared code for the judge-builder scripts. Runs on the firm's machine only.

The firm's finished work never leaves this machine except as the calls to Claude these scripts make with the
firm's own API key. What goes back to taskout is ids, verdicts, causes, rule ids and the judge's instructions,
scanned for identifiers first.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

SKILL_VERSION = "1.0.0"
JOBS_DIR = "taskout-jobs"
JOBS_DIR_ENV = "TASKOUT_JOBS_DIR"
WORK_LIMIT = 60_000  # characters of work.md sent to the judge per job
NOTES_LIMIT = 4_000
DEFAULT_MODEL = "claude-opus-5-5"
CAUSES = ["rule_broken", "rule_wrong", "rule_missing", "other"]
VERDICTS = ["accepted", "accepted_with_changes", "sent_back", "rejected"]


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def bucket(verdict: str) -> str:
    """Three ways a job holds up: accepted as is, accepted with changes, not accepted (sent back or rejected)."""
    return "not_accepted" if verdict in ("sent_back", "rejected") else verdict


def is_failure(verdict: str) -> bool:
    return bucket(verdict) == "not_accepted"


def jobs_dir(arg: str | None) -> Path:
    return Path(arg or os.environ.get(JOBS_DIR_ENV) or JOBS_DIR)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"{path} not found")
    except json.JSONDecodeError as e:
        fail(f"{path} is not valid JSON ({e.msg}, line {e.lineno})")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_examples(path: Path) -> dict:
    """The file downloaded from taskout (the playbook's How it's working tab, Download examples)."""
    data = read_json(path)
    if not isinstance(data, dict) or data.get("kind") != "taskout-judge-examples" or data.get("format") != 1:
        fail(f"{path} is not a taskout examples file (kind taskout-judge-examples, format 1)")
    return data


def load_job(root: Path, context_id: str) -> dict | None:
    """One finished job the agent saved (taskout-jobs/<context_id>/), or None when it isn't on this machine."""
    if not re.fullmatch(r"ctx_[0-9a-f]{32}", context_id):
        return None
    d = root / context_id
    work = d / "work.md"
    if not work.is_file():
        return None
    text = work.read_text(encoding="utf-8", errors="replace")
    notes_file = d / "review.md"
    notes = notes_file.read_text(encoding="utf-8", errors="replace")[:NOTES_LIMIT] if notes_file.is_file() else ""
    meta_file = d / "job.json"
    meta: dict = {}
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return {"work": text[:WORK_LIMIT], "truncated": len(text) > WORK_LIMIT, "notes": notes, "meta": meta if isinstance(meta, dict) else {}}


def render_rules(rules: list[dict]) -> str:
    """The rules of one playbook version, as the judge reads them (ids kept so a verdict can name a rule)."""
    out = []
    for r in rules:
        out.append(f"## {r['topic']} (rule {r['id']})")
        if r.get("guidance"):
            out.append(r["guidance"])
        for p in r.get("positions", []):
            cond = f" When: {p['conditions']}" if p.get("conditions") else ""
            out.append(f"- {p['tier']}: {p['text']}{cond}")
        if r.get("escalation"):
            out.append(f"- ask a person: {r['escalation']}")
        out.append("")
    return "\n".join(out).strip()


def held_out(context_id: str) -> bool:
    """A fixed third of the sampled jobs, by a hash of the job, is kept back to measure the judge. GEPA never sees it."""
    return int(hashlib.sha256(f"{context_id}|held-out".encode()).hexdigest()[:8], 16) % 3 == 0


def in_val(context_id: str) -> bool:
    """Within the rest, about 3 in 10 go to GEPA's own validation set (it picks candidates on those)."""
    return int(hashlib.sha256(f"{context_id}|val".encode()).hexdigest()[:8], 16) % 10 < 3


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Shapes of identifiers that must never leave in a judge's instructions or a proposed rule. taskout checks again,
# with the firm's client names, and refuses the whole file on any hit.
_SCANS = [
    ("NON_FICTIONAL_SSN", re.compile(r"\b(?!000)\d{3}-\d{2}-\d{4}\b")),
    ("NON_FICTIONAL_EIN", re.compile(r"\b(?!00)\d{2}-\d{7}\b")),
    ("NON_FICTIONAL_EMAIL", re.compile(r"\b[\w.+-]+@(?![\w-]*\.?example\.(?:com|org|net)\b)[\w-]+\.[\w.-]+\b")),
    ("NON_FICTIONAL_PHONE", re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    ("UNEXPLAINED_LONG_NUMBER", re.compile(r"\d{9,}")),
]


def scan(text: str) -> list[str]:
    plain = re.sub(r"\d{1,3}(,\d{3})+", "", text)
    return sorted({code for code, rx in _SCANS if rx.search(plain if code == "UNEXPLAINED_LONG_NUMBER" else text)})


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "cause": {"type": "string", "enum": CAUSES + ["none"]},
        "defect_rule_ids": {"type": "array", "items": {"type": "string"}},
        "severe": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "cause", "defect_rule_ids", "severe", "reason"],
    "additionalProperties": False,
}

JUDGE_FORMAT = """Answer with:
- verdict: accepted (a reviewer would pass it as is), accepted_with_changes, sent_back or rejected;
- cause, when not accepted as is: rule_broken (a rule wasn't followed), rule_wrong (the rules were followed and the
  work is still wrong), rule_missing (no rule covers what went wrong) or other; none when accepted as is;
- defect_rule_ids: the ids of the rules at fault, for rule_broken and rule_wrong; else empty;
- severe: true when a mistake would have reached the client;
- reason: one or two sentences."""

SEED_PROMPT = """You review a piece of an accounting firm's finished work the way the firm's reviewer would, against the
firm's own rules for this kind of work. Read the rules, then the work and the positions the preparer says it took.
Check each rule that applies: was the preferred position taken, or a fallback only when its condition holds; was no
red-line position taken; did the preparer ask a person where a rule says to ask. Then say how the reviewer would
receive the work."""


def judge_user_message(rules_text: str, work: str) -> str:
    return f"# The firm's rules for this work\n\n{rules_text}\n\n# The finished work\n\n{work}"


def normalize_judgement(raw: dict, rule_ids: set[str]) -> dict:
    verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else "sent_back"
    cause = raw.get("cause") if raw.get("cause") in CAUSES else None
    if verdict == "accepted":
        cause = None
    elif cause is None and is_failure(verdict):
        cause = "other"
    rules = [r for r in raw.get("defect_rule_ids") or [] if r in rule_ids] if cause in ("rule_broken", "rule_wrong") else []
    if cause in ("rule_broken", "rule_wrong") and not rules:
        cause = "other"
    return {"verdict": verdict, "cause": cause, "defect_rule_ids": rules, "severe": bool(raw.get("severe")), "reason": str(raw.get("reason") or "")[:600]}


# ---------------------------------------------------------------------------------------------------- Claude
# A judge call and a reflection call. Injected as plain functions so the tests run without a network.
JudgeLM = Callable[[str, str], dict]  # (system, user) -> the judge's JSON answer
ReflectLM = Callable[[str], str]  # prompt -> text


class RefusedError(Exception):
    pass


def anthropic_client():
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        fail('the anthropic package is missing: pip install "anthropic>=2.6"')
    return anthropic.Anthropic()  # the firm's own key: ANTHROPIC_API_KEY, or an `ant auth login` profile


def _create(client, *, model: str, effort: str, system: str, user: str, schema: dict | None, max_tokens: int):
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "adaptive"},
        # On a policy decline, the API re-runs the request on Anthropic's recommended fallback model.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    config: dict = {"effort": effort}
    if schema:
        config["format"] = {"type": "json_schema", "schema": schema}
    kwargs["output_config"] = config
    resp = client.beta.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RefusedError(getattr(getattr(resp, "stop_details", None), "category", None) or "refused")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the answer was cut off (max_tokens)")
    return text


def claude_judge(model: str = DEFAULT_MODEL, effort: str = "medium") -> JudgeLM:
    client = anthropic_client()

    def call(system: str, user: str) -> dict:
        return json.loads(_create(client, model=model, effort=effort, system=system, user=user, schema=JUDGE_SCHEMA, max_tokens=16000))

    return call


def claude_reflect(model: str = DEFAULT_MODEL, effort: str = "high") -> ReflectLM:
    client = anthropic_client()

    def call(prompt: str | list) -> str:
        if not isinstance(prompt, str):  # GEPA may pass chat messages
            prompt = "\n\n".join(str(m.get("content", "")) for m in prompt if isinstance(m, dict))
        return _create(client, model=model, effort=effort, system="You improve instructions for a reviewer of an accounting firm's work.", user=prompt, schema=None, max_tokens=32000)

    return call


def claude_json(model: str = DEFAULT_MODEL, effort: str = "high") -> Callable[[str, str, dict], dict]:
    client = anthropic_client()

    def call(system: str, user: str, schema: dict) -> dict:
        return json.loads(_create(client, model=model, effort=effort, system=system, user=user, schema=schema, max_tokens=32000))

    return call
