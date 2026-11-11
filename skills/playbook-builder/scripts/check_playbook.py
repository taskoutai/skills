#!/usr/bin/env python3
"""Check a playbook file before it is exported, shared or uploaded to taskout.

Usage: python3 check_playbook.py playbook.json [--redact redact.txt] [--report report.md] [--skills DIR] [--service service.json] [--fingerprint]
       python3 check_playbook.py --hash-skill SKILL_FOLDER

Checks the file format, real-looking identifiers, placeholder tokens and text that reads like
instructions to a model (taskout runs the same checks on upload), every entry in redact.txt (only
this machine can run that check), with --report that each citation id is in the report, and that a
local_test is of exactly these rules, with --skills that each of firm_skills is in DIR/<name>/SKILL.md
unchanged, and, for a client file, with --service that each rule's replaces is a topic of that service playbook. --fingerprint prints the rules' fingerprint for local_test; --hash-skill prints a skill's
name and SKILL.md hash for firm_skills.
Prints field paths and check codes only, never the text. Exit 0 = passed, 1 = findings, 2 = usage.
Standard library only; no network.
"""
import hashlib
import json
import re
import sys

FORMAT = "taskout.playbook"
FORMAT_VERSION = "2"
TIERS = {"preferred", "fallback", "unacceptable"}
ACTIVITY = re.compile(r"^[a-z_]+\.[a-z_.]+$")
REF = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
CLIENT_REF = re.compile(r"^[A-Za-z0-9._:-]{1,60}$")
OUTCOMES = {"", "approve", "reject", "answer"}
SKILL_VERSION = re.compile(r"^[0-9A-Za-z.+-]{1,40}$")
SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STATED_VS_PRACTICE = {"", "agree", "stated_only", "practice_only", "conflict"}

SSN = re.compile(r"(?<![\d-])(\d{3})-(\d{2})-(\d{4})(?![\d-])")
EIN = re.compile(r"(?<![\d-])(\d{2})-(\d{7})(?![\d-])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
FICTIONAL_EMAIL = re.compile(r"(^|\.)example\.(com|org|net)$|\.example$", re.I)
PHONE = re.compile(r"\(?\b(\d{3})\)?[-. ](\d{3})[-. ](\d{4})\b")
LONG_DIGITS = re.compile(r"\b\d{9,}\b")
GROUPED = re.compile(r"\d{1,3}(,\d{3})+")
MONEY = re.compile(r"\$?\(?-?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?\)?")
TOKENS = re.compile(r"PARTY_\d+|\[(SSN|EIN|EMAIL|PHONE|ID|AMOUNT)\]")
INSTRUCTION_LIKE = re.compile(
    r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|prompts?|guardrails)\b"
    r"|\bsystem prompt\b|</?(system|assistant|user|instructions?)>|\byou are now\b|\bdeveloper mode\b|\bjailbreak\b",
    re.I,
)

FIELDS = {
    "top": {"format", "format_version", "skill_version", "title", "general_guidance", "client_ref", "task_id", "precedent_count", "firm_skills", "rules", "workflow", "local_test"},
    "rule": {"topic", "activity_type", "guidance", "escalation", "positions", "stated_vs_practice", "tax_years", "replaces", "all_services", "client_exceptions"},
    "client_exception": {"client_ref", "text", "conditions", "comment", "support_matters", "client_matters", "citation_refs"},
    "workflow": {"steps", "edges"},
    "step": {"activity_type", "name", "description"},
    "edge": {"from", "to", "label", "outcome"},
    "position": {"tier", "text", "conditions", "comment", "support_matters", "citation_refs", "stated_refs", "doc_refs"},
    "firm_skill": {"name", "sha256"},
    "local_test": {"content_sha256", "held_out_matters", "readings_confirmed", "results"},
    "result": {"rule", "matter", "predicted", "actual"},
}
SHA = re.compile(r"^[0-9a-f]{64}$")


def fingerprint(rules):
    """sha256 of the rules' content, the same way taskout computes it on import."""
    t = lambda v: (v or "").strip() if isinstance(v, str) else ""
    content = [
        [t(r.get("topic")), t(r.get("activity_type")), t(r.get("guidance")), t(r.get("escalation")),
         [[p.get("tier"), t(p.get("text")), t(p.get("conditions")), t(p.get("comment"))] for p in r.get("positions") or [] if isinstance(p, dict)]]
        for r in rules if isinstance(r, dict)
    ]
    return hashlib.sha256(json.dumps(content, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def topic_key(v):
    """The rule's topic key, as taskout computes it: a client rule replaces the service rule with the same key."""
    parts = [re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", x)) for x in (v or "").lower().split(".")]
    return ".".join(x for x in parts if x)[:80]


def tax_years_ok(v):
    """'' (any year), '2025', '2023-2025', '2026-' (from) or '-2024' (up to), years 1900-2200."""
    if not isinstance(v, str) or len(v.strip()) > 20:
        return False
    s = re.sub(r"\s+", "", v).replace("\u2013", "-").replace("\u2014", "-")
    if not s:
        return True
    m = re.fullmatch(r"([0-9]{4})?(-)?([0-9]{4})?", s)
    if not m or not (m.group(1) or m.group(3)) or (m.group(3) and not m.group(2)):
        return False
    lo = int(m.group(1)) if m.group(1) else None
    hi = (int(m.group(3)) if m.group(3) else None) if m.group(2) else lo
    if any(y is not None and not 1900 <= y <= 2200 for y in (lo, hi)):
        return False
    return lo is None or hi is None or lo <= hi


def is_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def text_ok(v, lo, hi):
    return isinstance(v, str) and lo <= len(v.strip()) <= hi


def schema_findings(f):
    out = []
    if not isinstance(f, dict):
        return [("SCHEMA_NOT_AN_OBJECT", "")]
    for k in f:
        if k not in FIELDS["top"]:
            out.append(("SCHEMA_UNKNOWN_FIELD", k))
    if f.get("format") != FORMAT:
        out.append(("SCHEMA_FORMAT", "format"))
    if f.get("format_version") != FORMAT_VERSION:
        out.append(("SCHEMA_FORMAT_VERSION", "format_version"))
    if not isinstance(f.get("skill_version"), str) or not SKILL_VERSION.match(f["skill_version"]):
        out.append(("SCHEMA_SKILL_VERSION", "skill_version"))
    if not text_ok(f.get("title"), 2, 200):
        out.append(("SCHEMA_TEXT", "title"))
    if "general_guidance" in f and not text_ok(f["general_guidance"], 0, 4000):
        out.append(("SCHEMA_TEXT", "general_guidance"))
    client = "client_ref" in f
    if client and (not isinstance(f["client_ref"], str) or not CLIENT_REF.match(f["client_ref"].strip())):
        out.append(("SCHEMA_CLIENT_REF", "client_ref"))
    if "task_id" in f and (not client or not isinstance(f["task_id"], str) or not re.fullmatch(r"task_[0-9a-f]{32}", f["task_id"])):
        out.append(("SCHEMA_TASK_ID" if client else "TASK_ID_NEEDS_CLIENT_REF", "task_id"))
    if client:
        # One client's rules: no workflow (a client's rule set isn't run as a service), no firm skills, no exceptions.
        for k in ("workflow", "firm_skills"):
            if f.get(k):
                out.append(("NOT_IN_A_CLIENT_FILE", k))
    n = f.get("precedent_count")
    if not is_int(n, 0 if client else 1, 200):
        out.append(("SCHEMA_PRECEDENT_COUNT", "precedent_count"))
        n = 200
    skills = f.get("firm_skills", [])
    if not isinstance(skills, list) or len(skills) > 20:
        out.append(("SCHEMA_FIRM_SKILLS", "firm_skills"))
        skills = []
    seen_skills = set()
    for k, x in enumerate(skills):
        q = "firm_skills.%d" % k
        if not isinstance(x, dict):
            out.append(("SCHEMA_NOT_AN_OBJECT", q))
            continue
        out += [("SCHEMA_UNKNOWN_FIELD", q + "." + key) for key in x if key not in FIELDS["firm_skill"]]
        name = x.get("name")
        if not isinstance(name, str) or len(name) > 64 or not SKILL_NAME.match(name):
            out.append(("SCHEMA_FIRM_SKILL_NAME", q + ".name"))
        elif name in seen_skills:
            out.append(("SCHEMA_FIRM_SKILL_REPEATED", q + ".name"))
        else:
            seen_skills.add(name)
        if not isinstance(x.get("sha256"), str) or not SHA.match(x["sha256"]):
            out.append(("SCHEMA_FIRM_SKILL_SHA256", q + ".sha256"))
    rules = f.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 60:
        out.append(("SCHEMA_RULES", "rules"))
        rules = rules if isinstance(rules, list) else []
    for i, r in enumerate(rules):
        p = "rules.%d" % i
        if not isinstance(r, dict):
            out.append(("SCHEMA_NOT_AN_OBJECT", p))
            continue
        for k in r:
            if k not in FIELDS["rule"]:
                out.append(("SCHEMA_UNKNOWN_FIELD", p + "." + k))
        if not text_ok(r.get("topic"), 2, 200):
            out.append(("SCHEMA_TEXT", p + ".topic"))
        if not isinstance(r.get("activity_type"), str) or len(r["activity_type"]) > 80 or not ACTIVITY.match(r["activity_type"]):
            out.append(("SCHEMA_ACTIVITY_TYPE", p + ".activity_type"))
        if "tax_years" in r and not tax_years_ok(r["tax_years"]):
            out.append(("SCHEMA_TAX_YEARS", p + ".tax_years"))
        if "replaces" in r:
            if not client:
                out.append(("REPLACES_NEEDS_CLIENT_REF", p + ".replaces"))
            elif not text_ok(r["replaces"], 2, 200):
                out.append(("SCHEMA_TEXT", p + ".replaces"))
        if "all_services" in r:
            if not isinstance(r["all_services"], bool):
                out.append(("SCHEMA_ALL_SERVICES", p + ".all_services"))
            elif r["all_services"] and not client:
                out.append(("ALL_SERVICES_NEEDS_CLIENT_REF", p + ".all_services"))
        if client and r.get("client_exceptions"):
            out.append(("NOT_IN_A_CLIENT_FILE", p + ".client_exceptions"))
        for k, hi in (("guidance", 2000), ("escalation", 1000)):
            if k in r and not text_ok(r[k], 0, hi):
                out.append(("SCHEMA_TEXT", p + "." + k))
        positions = r.get("positions")
        if not isinstance(positions, list) or not 1 <= len(positions) <= 6:
            out.append(("SCHEMA_POSITIONS", p + ".positions"))
            positions = positions if isinstance(positions, list) else []
        if sum(1 for x in positions if isinstance(x, dict) and x.get("tier") == "preferred") > 1:
            out.append(("SCHEMA_TWO_PREFERRED", p + ".positions"))
        for j, x in enumerate(positions):
            q = "%s.positions.%d" % (p, j)
            if not isinstance(x, dict):
                out.append(("SCHEMA_NOT_AN_OBJECT", q))
                continue
            for k in x:
                if k not in FIELDS["position"]:
                    out.append(("SCHEMA_UNKNOWN_FIELD", q + "." + k))
            if x.get("tier") not in TIERS:
                out.append(("SCHEMA_TIER", q + ".tier"))
            if not text_ok(x.get("text"), 3, 3000):
                out.append(("SCHEMA_TEXT", q + ".text"))
            for k in ("conditions", "comment"):
                if k in x and not text_ok(x[k], 0, 1000):
                    out.append(("SCHEMA_TEXT", q + "." + k))
            if not is_int(x.get("support_matters"), 0, 200):
                out.append(("SCHEMA_SUPPORT", q + ".support_matters"))
            elif x["support_matters"] > n:
                out.append(("SCHEMA_SUPPORT_EXCEEDS_PRECEDENTS", q + ".support_matters"))
            refs = x.get("citation_refs", [])
            if not isinstance(refs, list) or len(refs) > 30 or not all(isinstance(c, str) and REF.match(c) for c in refs):
                out.append(("SCHEMA_CITATION_REFS", q + ".citation_refs"))
            stated = x.get("stated_refs", [])
            if not isinstance(stated, list) or len(stated) > 30 or not all(isinstance(c, str) and REF.match(c) for c in stated):
                out.append(("SCHEMA_STATED_REFS", q + ".stated_refs"))
            elif stated and not skills:
                out.append(("STATED_NEEDS_FIRM_SKILLS", q + ".stated_refs"))
            docs = x.get("doc_refs", [])
            if not isinstance(docs, list) or len(docs) > 30 or not all(isinstance(c, str) and REF.match(c) for c in docs):
                out.append(("SCHEMA_DOC_REFS", q + ".doc_refs"))
            elif docs and not client:
                out.append(("DOC_REFS_NEED_CLIENT_REF", q + ".doc_refs"))
            elif client and not docs and not is_int(x.get("support_matters"), 1, 200):
                # A client's position rests on its documents or its past engagements, never on nothing.
                out.append(("NO_EVIDENCE", q))
        out += stated_vs_practice_findings(r, p, positions, bool(skills))
        out += client_exception_findings(r.get("client_exceptions", []), p, n)
    if client:
        keys = [topic_key(r.get("replaces") or r.get("topic")) if isinstance(r, dict) else "" for r in rules]
        for i, k in enumerate(keys):
            if isinstance(rules[i], dict) and not k:
                out.append(("TOPIC_KEY_EMPTY", "rules.%d" % i))
            elif k and keys.index(k) != i:
                out.append(("TOPIC_REPEATED", "rules.%d" % i))
    if "workflow" in f and not client:
        out += workflow_findings(f["workflow"])
    t = f.get("local_test")
    if t is not None:
        out += local_test_findings(t, rules)
    return out


def stated_vs_practice_findings(r, p, positions, have_skills):
    """How the rule compares with the firm's skills, matching what its positions cite (as taskout checks on import)."""
    svp = r.get("stated_vs_practice", "")
    q = p + ".stated_vs_practice"
    if svp not in STATED_VS_PRACTICE:
        return [("SCHEMA_STATED_VS_PRACTICE", q)]
    if not have_skills:
        return [("STATED_NEEDS_FIRM_SKILLS", q)] if svp else []
    if not svp:
        return [("STATED_VS_PRACTICE_MISSING", q)]
    ps = [x for x in positions if isinstance(x, dict)]
    stated = any(isinstance(x.get("stated_refs"), list) and x["stated_refs"] for x in ps)
    practice = any(is_int(x.get("support_matters"), 1, 200) for x in ps)
    ok = {
        "stated_only": stated and not practice,
        "practice_only": not stated,
        "agree": stated and practice,
        "conflict": stated and practice,
    }[svp]
    return [] if ok else [("STATED_VS_PRACTICE_MISMATCH", q)]


def client_exception_findings(xs, p, n):
    out = []
    if not isinstance(xs, list) or len(xs) > 30:
        return [("SCHEMA_CLIENT_EXCEPTIONS", p + ".client_exceptions")]
    seen = set()
    for k, x in enumerate(xs):
        q = "%s.client_exceptions.%d" % (p, k)
        if not isinstance(x, dict):
            out.append(("SCHEMA_NOT_AN_OBJECT", q))
            continue
        for key in x:
            if key not in FIELDS["client_exception"]:
                out.append(("SCHEMA_UNKNOWN_FIELD", q + "." + key))
        ref = x.get("client_ref")
        if not isinstance(ref, str) or not CLIENT_REF.match(ref.strip()):
            out.append(("SCHEMA_CLIENT_REF", q + ".client_ref"))
        elif ref in seen:
            out.append(("SCHEMA_CLIENT_REPEATED", q + ".client_ref"))
        else:
            seen.add(ref)
        if not text_ok(x.get("text"), 3, 3000):
            out.append(("SCHEMA_TEXT", q + ".text"))
        for key in ("conditions", "comment"):
            if key in x and not text_ok(x[key], 0, 1000):
                out.append(("SCHEMA_TEXT", q + "." + key))
        cm = x.get("client_matters")
        if not is_int(cm, 1, 200) or cm > n:
            out.append(("SCHEMA_CLIENT_MATTERS", q + ".client_matters"))
            cm = 200
        if not is_int(x.get("support_matters"), 1, 200) or x["support_matters"] > cm:
            out.append(("SCHEMA_SUPPORT", q + ".support_matters"))
        refs = x.get("citation_refs", [])
        if not isinstance(refs, list) or len(refs) > 30 or not all(isinstance(c, str) and REF.match(c) for c in refs):
            out.append(("SCHEMA_CITATION_REFS", q + ".citation_refs"))
    return out


def workflow_findings(w):
    if not isinstance(w, dict):
        return [("SCHEMA_NOT_AN_OBJECT", "workflow")]
    out = [("SCHEMA_UNKNOWN_FIELD", "workflow." + k) for k in w if k not in FIELDS["workflow"]]
    steps = w.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 40:
        out.append(("SCHEMA_WORKFLOW_STEPS", "workflow.steps"))
        steps = steps if isinstance(steps, list) else []
    types = set()
    for k, st in enumerate(steps):
        q = "workflow.steps.%d" % k
        if not isinstance(st, dict):
            out.append(("SCHEMA_NOT_AN_OBJECT", q))
            continue
        out += [("SCHEMA_UNKNOWN_FIELD", q + "." + key) for key in st if key not in FIELDS["step"]]
        a = st.get("activity_type")
        if not isinstance(a, str) or len(a) > 80 or not ACTIVITY.match(a):
            out.append(("SCHEMA_ACTIVITY_TYPE", q + ".activity_type"))
        elif a in types:
            out.append(("SCHEMA_STEP_REPEATED", q + ".activity_type"))
        else:
            types.add(a)
        if not text_ok(st.get("name"), 3, 80):
            out.append(("SCHEMA_TEXT", q + ".name"))
        if "description" in st and not text_ok(st["description"], 0, 600):
            out.append(("SCHEMA_TEXT", q + ".description"))
    edges = w.get("edges", [])
    if not isinstance(edges, list) or len(edges) > 200:
        return out + [("SCHEMA_WORKFLOW_EDGES", "workflow.edges")]
    seen = set()
    node = lambda v, end: v == end or is_int(v, 0, len(steps) - 1)
    for k, e in enumerate(edges):
        q = "workflow.edges.%d" % k
        if not isinstance(e, dict):
            out.append(("SCHEMA_NOT_AN_OBJECT", q))
            continue
        out += [("SCHEMA_UNKNOWN_FIELD", q + "." + key) for key in e if key not in FIELDS["edge"]]
        if not node(e.get("from"), "start") or not node(e.get("to"), "end") or e.get("from") == e.get("to"):
            out.append(("SCHEMA_EDGE", q))
        if "label" in e and not text_ok(e["label"], 0, 120):
            out.append(("SCHEMA_TEXT", q + ".label"))
        if e.get("outcome", "") not in OUTCOMES:
            out.append(("SCHEMA_EDGE_OUTCOME", q + ".outcome"))
        key = (repr(e.get("from")), repr(e.get("to")), e.get("outcome", ""))
        if key in seen:
            out.append(("SCHEMA_EDGE_REPEATED", q))
        seen.add(key)
    nxt = {}
    for e in edges:
        if isinstance(e, dict):
            nxt.setdefault(repr(e.get("from")), []).append(repr(e.get("to")))
    state = {}

    def cyclic(n):
        if state.get(n) == 2:
            return False
        if state.get(n) == 1:
            return True
        state[n] = 1
        found = any(cyclic(t) for t in nxt.get(n, []))
        state[n] = 2
        return found

    if any(cyclic(n) for n in list(nxt)):
        out.append(("SCHEMA_WORKFLOW_CYCLE", "workflow.edges"))
    return out


def local_test_findings(t, rules):
    if not isinstance(t, dict) or set(t) != FIELDS["local_test"]:
        return [("SCHEMA_LOCAL_TEST", "local_test")]
    out = []
    if not isinstance(t["content_sha256"], str) or not SHA.match(t["content_sha256"]):
        out.append(("SCHEMA_LOCAL_TEST", "local_test.content_sha256"))
    elif t["content_sha256"] != fingerprint(rules):
        out.append(("LOCAL_TEST_STALE", "local_test.content_sha256"))
    n = t["held_out_matters"]
    if not is_int(n, 1, 50):
        out.append(("SCHEMA_LOCAL_TEST", "local_test.held_out_matters"))
        n = 50
    if t["readings_confirmed"] is not True:
        out.append(("LOCAL_TEST_NOT_CONFIRMED", "local_test.readings_confirmed"))
    results = t["results"]
    if not isinstance(results, list) or not 1 <= len(results) <= 3000:
        return out + [("SCHEMA_LOCAL_TEST", "local_test.results")]
    seen = set()
    for k, x in enumerate(results):
        q = "local_test.results.%d" % k
        if not isinstance(x, dict) or set(x) != FIELDS["result"]:
            out.append(("SCHEMA_LOCAL_TEST_RESULT", q))
            continue
        rule = rules[x["rule"]] if is_int(x["rule"], 0, 59) and x["rule"] < len(rules) and isinstance(rules[x["rule"]], dict) else None
        positions = rule.get("positions") if rule else None
        npos = len(positions) if isinstance(positions, list) else 0
        if rule is None or not is_int(x["matter"], 1, n) or (x["rule"], x["matter"]) in seen:
            out.append(("SCHEMA_LOCAL_TEST_RESULT", q))
        elif any(x[p] is not None and not is_int(x[p], 0, npos - 1) for p in ("predicted", "actual")):
            out.append(("SCHEMA_LOCAL_TEST_RESULT", q))
        seen.add((x["rule"], x["matter"]))
    return out


def text_fields(f):
    yield "title", f.get("title")
    yield "general_guidance", f.get("general_guidance")
    for k, x in enumerate(f.get("firm_skills") or [] if isinstance(f.get("firm_skills"), list) else []):
        if isinstance(x, dict):
            yield "firm_skills.%d.name" % k, x.get("name")
    for i, r in enumerate(f.get("rules") or []):
        if not isinstance(r, dict):
            continue
        for k in ("topic", "guidance", "escalation", "replaces"):
            yield "rules.%d.%s" % (i, k), r.get(k)
        for j, x in enumerate(r.get("positions") or []):
            if isinstance(x, dict):
                for k in ("text", "conditions", "comment"):
                    yield "rules.%d.positions.%d.%s" % (i, j, k), x.get(k)
        for j, x in enumerate(r.get("client_exceptions") or []):
            if isinstance(x, dict):
                for k in ("text", "conditions", "comment"):
                    yield "rules.%d.client_exceptions.%d.%s" % (i, j, k), x.get(k)
    w = f.get("workflow") if isinstance(f.get("workflow"), dict) else {}
    for k, st in enumerate(w.get("steps") or []):
        if isinstance(st, dict):
            for key in ("name", "description"):
                yield "workflow.steps.%d.%s" % (k, key), st.get(key)
    for k, e in enumerate(w.get("edges") or []):
        if isinstance(e, dict):
            yield "workflow.edges.%d.label" % k, e.get("label")


def money_cents(text):
    return {int(m.group(1).replace(",", "")) * 100 + int(m.group(2) or 0) for m in MONEY.finditer(text)}


def identifier_codes(text):
    codes = set()
    if any(m.group(1) != "000" for m in SSN.finditer(text)):
        codes.add("NON_FICTIONAL_SSN")
    if any(m.group(1) != "00" for m in EIN.finditer(text)):
        codes.add("NON_FICTIONAL_EIN")
    if any(not FICTIONAL_EMAIL.search(m.group(1)) for m in EMAIL.finditer(text)):
        codes.add("NON_FICTIONAL_EMAIL")
    if any(not (m.group(2) == "555" and m.group(3).startswith("01")) for m in PHONE.finditer(text)):
        codes.add("NON_FICTIONAL_PHONE")
    if LONG_DIGITS.search(GROUPED.sub("", text)):
        codes.add("UNEXPLAINED_LONG_NUMBER")
    if TOKENS.search(text):
        codes.add("PSEUDONYM_TOKEN_COPIED")
    if INSTRUCTION_LIKE.search(text):
        codes.add("INSTRUCTION_LIKE_TEXT")
    return codes


def load_redactions(path):
    names, cents = [], set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            v = line.strip()
            if not v or v.startswith("#"):
                continue
            if re.fullmatch(r"\$?\(?-?[\d,]+(\.\d{2})?\)?", v):
                cents |= money_cents(v)
            else:
                names.append(v.lower())
    return names, cents


def text_findings(f, names, cents):
    out = []
    for path, text in text_fields(f):
        if not isinstance(text, str) or not text:
            continue
        for code in sorted(identifier_codes(text)):
            out.append((code, path))
        lower = text.lower()
        if any(re.search(r"(^|[^a-z])" + re.escape(n) + r"([^a-z]|$)", lower) for n in names):
            out.append(("LEAK_CLIENT_NAME", path))
        if money_cents(text) & cents:
            out.append(("LEAK_CLIENT_AMOUNT", path))
    # Client references are the firm's own ids: they must not be a name or a taxpayer identifier.
    refs = [("client_ref", f.get("client_ref"))]
    for i, r in enumerate(f.get("rules") or []):
        for k, x in enumerate((r.get("client_exceptions") or []) if isinstance(r, dict) else []):
            ref = x.get("client_ref") if isinstance(x, dict) else None
            if not isinstance(ref, str) or not ref:
                continue
            refs.append(("rules.%d.client_exceptions.%d.client_ref" % (i, k), ref))
    for path, ref in refs:
        if not isinstance(ref, str) or not ref:
            continue
        for code in sorted(identifier_codes(ref) - {"INSTRUCTION_LIKE_TEXT"}):
            out.append((code, path))
        if any(re.search(r"(^|[^a-z])" + re.escape(n) + r"([^a-z]|$)", ref.lower()) for n in names):
            out.append(("LEAK_CLIENT_NAME", path))
    return out


def report_findings(f, report):
    out = []
    for i, r in enumerate(f.get("rules") or []):
        for kind in ("positions", "client_exceptions"):
            for j, x in enumerate((r.get(kind) or []) if isinstance(r, dict) else []):
                for field in ("citation_refs", "stated_refs", "doc_refs"):
                    for c in (x.get(field) or []) if isinstance(x, dict) and isinstance(x.get(field), list) else []:
                        if isinstance(c, str) and not re.search(r"(^|[^A-Za-z0-9_.-])" + re.escape(c) + r"([^A-Za-z0-9_.-]|$)", report):
                            out.append(("CITATION_NOT_IN_REPORT", "rules.%d.%s.%d.%s" % (i, kind, j, field)))
    return out


BLOCK_BEGIN = "<!-- taskout:begin"
BLOCK_END = "<!-- taskout:end -->"


def canonical_skill_text(text):
    """SKILL.md as taskout hashes it: LF line ends, without the block taskout's bind-skills.mjs appends, trailing
    whitespace cut to one newline. The same skill hashes the same before and after it is added to the plugin."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    i = 0 if t.startswith(BLOCK_BEGIN) else t.find("\n" + BLOCK_BEGIN)
    if i >= 0:
        j = t.find(BLOCK_END, i)
        if j >= 0:
            t = t[:i] + t[j + len(BLOCK_END):]
    return re.sub(r"[ \t\n\r\f\v]+\Z", "", t) + "\n"


def frontmatter_name(text):
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if not t.startswith("---\n"):
        return ""
    end = t.find("\n---", 4)
    if end < 0:
        return ""
    m = re.search(r"^name:[ \t]*[\"']?([^\"'\n]+?)[\"']?[ \t]*$", t[4:end], re.M)
    return m.group(1).strip() if m else ""


def skill_identity(folder):
    """(name from SKILL.md's frontmatter, sha256 of its canonical text), or None if there is no SKILL.md."""
    path = folder.rstrip("/\\") + "/SKILL.md"
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    return (frontmatter_name(text), hashlib.sha256(canonical_skill_text(text).encode("utf-8")).hexdigest())


def skills_findings(f, skills_dir):
    """Each of firm_skills must be DIR/<name>/SKILL.md, unchanged since the rules were compared with it."""
    out = []
    for k, x in enumerate(f.get("firm_skills") or [] if isinstance(f.get("firm_skills"), list) else []):
        if not isinstance(x, dict) or not isinstance(x.get("name"), str) or not SKILL_NAME.match(x["name"]):
            continue
        ident = skill_identity(skills_dir.rstrip("/\\") + "/" + x["name"])
        if ident is None or ident[0] != x["name"]:
            out.append(("FIRM_SKILL_NOT_FOUND", "firm_skills.%d" % k))
        elif ident[1] != x.get("sha256"):
            out.append(("FIRM_SKILL_CHANGED", "firm_skills.%d.sha256" % k))
    return out


def service_findings(f, service):
    """Each rule's replaces must be a topic of the service playbook (by topic key), or it would replace nothing."""
    topics = {topic_key(r.get("topic")) for r in (service.get("rules") or []) if isinstance(r, dict)} if isinstance(service, dict) else set()
    out = []
    for i, r in enumerate(f.get("rules") or []):
        if isinstance(r, dict) and isinstance(r.get("replaces"), str) and topic_key(r["replaces"]) not in topics:
            out.append(("REPLACES_NOT_FOUND", "rules.%d.replaces" % i))
    return out


def check(f, names=(), cents=frozenset(), report=None, skills_dir=None, service=None):
    findings = schema_findings(f)
    if isinstance(f, dict):
        findings += text_findings(f, list(names), set(cents))
        if report is not None:
            findings += report_findings(f, report)
        if skills_dir is not None:
            findings += skills_findings(f, skills_dir)
        if service is not None:
            findings += service_findings(f, service)
    return findings


def main(argv):
    args = argv[1:]
    if len(args) == 2 and args[0] == "--hash-skill":
        ident = skill_identity(args[1])
        if ident is None or not SKILL_NAME.match(ident[0]):
            print("FAIL FIRM_SKILL_NOT_FOUND")
            return 1
        print("%s %s" % ident)
        return 0
    if not args or args[0].startswith("-"):
        print(__doc__.strip().splitlines()[2])
        return 2
    opts = {"--redact": None, "--report": None, "--skills": None, "--service": None}
    rest = args[1:]
    show_fingerprint = "--fingerprint" in rest
    rest = [a for a in rest if a != "--fingerprint"]
    while rest:
        k = rest.pop(0)
        if k not in opts or not rest:
            print("unknown or incomplete option: " + k)
            return 2
        opts[k] = rest.pop(0)
    try:
        with open(args[0], encoding="utf-8") as fh:
            f = json.load(fh)
    except (OSError, ValueError):
        print("FAIL SCHEMA_INVALID_JSON")
        return 1
    if show_fingerprint:
        if not isinstance(f, dict) or not isinstance(f.get("rules"), list):
            print("FAIL SCHEMA_RULES rules")
            return 1
        print(fingerprint(f["rules"]))
        return 0
    names, cents = load_redactions(opts["--redact"]) if opts["--redact"] else ([], set())
    report = None
    if opts["--report"]:
        with open(opts["--report"], encoding="utf-8") as fh:
            report = fh.read()
    service = None
    if opts["--service"]:
        try:
            with open(opts["--service"], encoding="utf-8") as fh:
                service = json.load(fh)
        except (OSError, ValueError):
            print("FAIL SERVICE_INVALID_JSON")
            return 1
    findings = check(f, names, cents, report, opts["--skills"], service)
    for code, path in findings:
        print("FAIL %s %s" % (code, path))
    if not opts["--redact"]:
        print("WARN no --redact list: client names and amounts were not checked")
    if findings:
        print("%d finding(s). Fix playbook.json and run again." % len(findings))
        return 1
    print("OK: %d rule(s) passed." % len(f["rules"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
