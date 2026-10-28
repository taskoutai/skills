#!/usr/bin/env python3
"""Check a playbook file before it is exported, shared or uploaded to taskout.

Usage: python3 check_playbook.py playbook.json [--redact redact.txt] [--report report.md] [--fingerprint]

Checks the file format, real-looking identifiers, placeholder tokens and text that reads like
instructions to a model (taskout runs the same checks on upload), every entry in redact.txt (only
this machine can run that check), with --report that each citation id is in the report, and that a
local_test is of exactly these rules. --fingerprint prints the rules' fingerprint for local_test.
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
SKILL_VERSION = re.compile(r"^[0-9A-Za-z.+-]{1,40}$")

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
    "top": {"format", "format_version", "skill_version", "title", "general_guidance", "precedent_count", "rules", "local_test"},
    "rule": {"topic", "activity_type", "guidance", "escalation", "positions"},
    "position": {"tier", "text", "conditions", "comment", "support_matters", "citation_refs"},
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
    n = f.get("precedent_count")
    if not is_int(n, 1, 200):
        out.append(("SCHEMA_PRECEDENT_COUNT", "precedent_count"))
        n = 200
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
    t = f.get("local_test")
    if t is not None:
        out += local_test_findings(t, rules)
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
    for i, r in enumerate(f.get("rules") or []):
        if not isinstance(r, dict):
            continue
        for k in ("topic", "guidance", "escalation"):
            yield "rules.%d.%s" % (i, k), r.get(k)
        for j, x in enumerate(r.get("positions") or []):
            if isinstance(x, dict):
                for k in ("text", "conditions", "comment"):
                    yield "rules.%d.positions.%d.%s" % (i, j, k), x.get(k)


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
    return out


def report_findings(f, report):
    out = []
    for i, r in enumerate(f.get("rules") or []):
        for j, x in enumerate((r.get("positions") or []) if isinstance(r, dict) else []):
            for c in (x.get("citation_refs") or []) if isinstance(x, dict) else []:
                if isinstance(c, str) and not re.search(r"(^|[^A-Za-z0-9_.-])" + re.escape(c) + r"([^A-Za-z0-9_.-]|$)", report):
                    out.append(("CITATION_NOT_IN_REPORT", "rules.%d.positions.%d.citation_refs" % (i, j)))
    return out


def check(f, names=(), cents=frozenset(), report=None):
    findings = schema_findings(f)
    if isinstance(f, dict):
        findings += text_findings(f, list(names), set(cents))
        if report is not None:
            findings += report_findings(f, report)
    return findings


def main(argv):
    args = argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__.strip().splitlines()[2])
        return 2
    opts = {"--redact": None, "--report": None}
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
    findings = check(f, names, cents, report)
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
