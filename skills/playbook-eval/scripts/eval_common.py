"""Shared code for the playbook-eval scripts. Runs on the firm's machine only.

The engagements, the agents' work and the firm's deliverables never leave this machine except as the calls these
scripts make with the firm's own Claude key (Claude Code runs and judge calls). What can be shared is
result.json: counts, rule topics, skill names and hashes, scanned for identifiers first.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

SKILL_VERSION = "1.1.0"
STATE = Path(".playbook-eval")
DEFAULT_MODEL = "claude-opus-5-5"
TEXT_LIMIT = 60_000  # characters of documents, work or deliverables sent to the judge per side
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".eml", ".html", ".htm", ".xml", ".tsv", ".yaml", ".yml"}
BLOCK_BEGIN = "<!-- taskout:begin"
BLOCK_END = "<!-- taskout:end -->"
NOT_TOUCHED = "not_touched"


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


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


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_setup(state: Path = STATE) -> dict:
    data = read_json(state / "eval.json")
    if not isinstance(data, dict) or data.get("kind") != "taskout-playbook-eval-setup" or data.get("format") != 1:
        fail(f"{state / 'eval.json'} is not a playbook-eval setup: run setup_eval.py first")
    return data


# ------------------------------------------------------------------------------------------------ skills
def canonical_skill_text(text: str) -> str:
    """SKILL.md as taskout hashes it (same as check_playbook.py --hash-skill): LF line ends, without the block
    taskout's bind-skills.mjs appends, trailing whitespace cut to one newline."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    i = 0 if t.startswith(BLOCK_BEGIN) else t.find("\n" + BLOCK_BEGIN)
    if i >= 0:
        j = t.find(BLOCK_END, i)
        if j >= 0:
            t = t[:i] + t[j + len(BLOCK_END):]
    return re.sub(r"[ \t\n\r\f\v]+\Z", "", t) + "\n"


def frontmatter(text: str) -> dict:
    t = text.replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    if not m:
        return {}
    out = {}
    for k, v in re.findall(r"^\s*([a-z0-9-]+): ?(.*)$", m.group(1), re.M):
        v = v.strip()
        out[k] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
    return out


def skill_folders(path: Path) -> list[Path]:
    """A skill folder (holds SKILL.md), or a folder of skill folders."""
    if (path / "SKILL.md").is_file():
        return [path]
    if path.is_dir():
        found = sorted(p for p in path.iterdir() if (p / "SKILL.md").is_file())
        if found:
            return found
    fail(f"{path} is not a skill folder (no SKILL.md) or a folder of skill folders")
    return []


def describe_skill(folder: Path) -> dict:
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    front = frontmatter(text)
    name = front.get("name") or folder.name
    return {"name": name, "path": str(folder.resolve()), "sha256": sha256(canonical_skill_text(text)), "rules_sha256": front.get("rules-sha256") or None}


# ------------------------------------------------------------------------------------------------ rubric
def load_rubric(path: Path) -> dict:
    """playbook.json (from the playbook-builder, or a version downloaded from taskout for testing)."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list) or not data["rules"]:
        fail(f"{path} has no rules: pass the playbook.json the playbook-builder wrote, or a version downloaded for testing")
    for i, r in enumerate(data["rules"]):
        if not isinstance(r, dict) or not r.get("topic") or not isinstance(r.get("positions"), list) or not r["positions"]:
            fail(f"{path}: rule {i} needs a topic and positions")
    return data


def render_rules(rules: list[dict]) -> str:
    """The rules as the judge reads them: numbered rules, numbered positions, so an answer can name both."""
    out = []
    for i, r in enumerate(rules):
        out.append(f"## Rule {i}: {r['topic']}")
        if r.get("guidance"):
            out.append(str(r["guidance"]))
        for j, p in enumerate(r["positions"]):
            tier = {"unacceptable": "red line"}.get(p.get("tier"), p.get("tier", "position"))
            cond = f" When: {p['conditions']}" if p.get("conditions") else ""
            out.append(f"- position {j} ({tier}): {p.get('text', '')}{cond}")
        if r.get("escalation"):
            out.append(f"- ask a person: {r['escalation']}")
        out.append("")
    return "\n".join(out).strip()


def red_lines(rules: list[dict]) -> set[tuple[int, int]]:
    return {(i, j) for i, r in enumerate(rules) for j, p in enumerate(r["positions"]) if p.get("tier") == "unacceptable"}


# ------------------------------------------------------------------------------------------------ files
def read_tree(folder: Path, limit: int = TEXT_LIMIT) -> tuple[str, list[str]]:
    """The text files under a folder, each under its relative path, cut at `limit` characters in all. Returns the
    text and the files it couldn't read as text (PDFs, spreadsheets: convert them first, see SKILL.md)."""
    parts, skipped, used = [], [], 0
    if not folder.is_dir():
        return "", []
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = str(f.relative_to(folder))
        if f.name.startswith(".") or "__pycache__" in f.parts:
            continue
        if f.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(rel)
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        block = f"=== {rel} ===\n{body}\n"
        if used + len(block) > limit:
            parts.append(block[: max(0, limit - used)] + "\n[cut: the rest was too long]\n")
            break
        parts.append(block)
        used += len(block)
    return "".join(parts), skipped


# ------------------------------------------------------------------------------------------------ scans
# Shapes of identifiers that must never be in result.json. The report keeps cases by number, never by name.
_SCANS = [
    ("NON_FICTIONAL_SSN", re.compile(r"\b(?!000)\d{3}-\d{2}-\d{4}\b")),
    ("NON_FICTIONAL_EIN", re.compile(r"\b(?!00)\d{2}-\d{7}\b")),
    ("NON_FICTIONAL_EMAIL", re.compile(r"\b[\w.+-]+@(?![\w-]*\.?example\.(?:com|org|net)\b)[\w-]+\.[\w.-]+\b")),
    ("NON_FICTIONAL_PHONE", re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
]


def scan(text: str) -> list[str]:
    return sorted({code for code, rx in _SCANS if rx.search(text)})


# ------------------------------------------------------------------------------------------------ stats
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}


def t95(df: int) -> float:
    if df <= 0:
        return float("nan")
    keys = sorted(T95)
    for k in keys:
        if df <= k:
            return T95[k]
    return 1.960


def mean_ci(xs: list[float]) -> dict:
    """Mean with a 95% t interval (paired differences are passed in as one list)."""
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "low": None, "high": None}
    m = sum(xs) / n
    if n == 1:
        return {"n": 1, "mean": m, "low": None, "high": None}
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    half = t95(n - 1) * (var / n) ** 0.5
    return {"n": n, "mean": m, "low": m - half, "high": m + half}


def wilson(k: float, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"n": 0, "rate": None, "low": None, "high": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return {"n": n, "rate": p, "low": max(0.0, c - h), "high": min(1.0, c + h)}


# ------------------------------------------------------------------------------------------------ Claude
JsonLM = Callable[[str, str, dict], dict]  # (system, user, schema) -> JSON answer


class RefusedError(Exception):
    pass


def anthropic_client():
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        fail('the anthropic package is missing: pip install "anthropic>=2.6"')
    return anthropic.Anthropic()  # the firm's own key: ANTHROPIC_API_KEY


def claude_json(model: str = DEFAULT_MODEL, effort: str = "high") -> JsonLM:
    client = anthropic_client()

    def call(system: str, user: str, schema: dict) -> dict:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=32000,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # On a policy decline, the API re-runs the request on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RefusedError(getattr(getattr(resp, "stop_details", None), "category", None) or "refused")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("the answer was cut off (max_tokens)")
        return json.loads("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))

    return call
