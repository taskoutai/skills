#!/usr/bin/env python3
"""Turn a checked playbook.json into files the team's AI agents use.

Usage: python3 export_playbook.py playbook.json [--out DIR] [--name NAME] [--redact redact.txt]

Writes, under DIR (default: playbook-export):
  NAME/SKILL.md, NAME/activities/*.md   an Agent Skill: copy NAME/ into the agent's skills folder
  PLAYBOOK.md                           the same rules in one file, for any AI model or AGENTS.md
NAME defaults to the title in lowercase with hyphens. Runs check_playbook.py's checks first and
writes nothing if any fails. Exit 0 = written, 1 = findings, 2 = usage. Standard library only.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_playbook  # noqa: E402

GENERATOR = "playbook-builder"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TIER_LABEL = {"preferred": "Preferred", "fallback": "Fallback", "unacceptable": "Never"}
TIER_ORDER = {"preferred": 0, "fallback": 1, "unacceptable": 2}
CODE = chr(96)
CLIENT_NOTE = "Where a rule names a client, follow that client's position for that client's work instead of the preferred one. Red lines still apply."
OUTCOME = {"approve": "approves", "reject": "rejects", "answer": "answers"}


def client_note(ref):
    return ("These rules are for client %s%s%s only. Where one says which of the team's rules it replaces, or has the same topic as one, "
            "follow it for this client's work instead. Red lines from both still apply." % (CODE, one_line(ref), CODE))


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:64].rstrip("-")
    return s or "team-playbook"


def one_line(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def sentence(text):
    t = one_line(text)
    return t if not t or t[-1] in ".!?" else t + "."


def activities(rules):
    """Rules grouped by activity_type, in the playbook's workflow order."""
    groups = {}
    for i, r in enumerate(rules):
        groups.setdefault(r["activity_type"], []).append((i, r))
    return groups


def description(f, groups):
    """The skill's description: what it is and when to use it, at most 1024 characters."""
    title = one_line(f["title"])
    ref = one_line(f["client_ref"]) if "client_ref" in f else ""
    if ref:
        head = ("The team's own rules for client %s (%s): what to do for this client's work, from its own documents and past engagements, "
                "red lines and when to escalate. Use when doing, planning or reviewing any work for client %s" % (ref, title, ref))
    else:
        head = "The team's own rules for %s: preferred approaches, accepted fallbacks and when they apply, red lines and when to escalate. Use when doing, planning or reviewing %s work" % (title, title)
    topics = [one_line(r["topic"]) for r in f["rules"]]
    out = head + "."
    for k in range(len(topics), 0, -1):
        more = "" if k == len(topics) else ", and related work"
        candidate = "%s, including %s%s." % (head, "; ".join(topics[:k]), more)
        if len(candidate) <= 1024:
            out = candidate
            break
    return out[:1024]


def support(p, n, client):
    out = " (stated in the client's documents)" if p.get("doc_refs") else ""
    s = p.get("support_matters")
    if isinstance(s, int) and not isinstance(s, bool) and s > 0:
        out += (" (seen in %d of the client's %d past engagements)" if client else " (seen in %d of %d past engagements)") % (s, n)
    return out


def years_text(v):
    """'2025' -> '2025'; '2023-2025' -> '2023 to 2025'; '2026-' -> '2026 and later'; '-2024' -> '2024 and earlier'."""
    t = re.sub(r"\s+", "", v or "").replace("\u2013", "-").replace("\u2014", "-")
    m = re.fullmatch(r"([0-9]{4})?(-)?([0-9]{4})?", t)
    if not t or not m or not (m.group(1) or m.group(3)):
        return ""
    lo, dash, hi = m.group(1), m.group(2), m.group(3)
    if not dash:
        return lo
    if lo and hi:
        return lo if lo == hi else "%s to %s" % (lo, hi)
    return ("%s and later" % lo) if lo else ("%s and earlier" % hi)


def rule_md(r, n, level="##", client=False):
    lines = ["%s %s" % (level, one_line(r["topic"])), ""]
    if one_line(r.get("guidance")):
        lines += [sentence(r["guidance"]), ""]
    for p in sorted(r["positions"], key=lambda p: TIER_ORDER[p["tier"]]):
        line = "- **%s:** %s" % (TIER_LABEL[p["tier"]], sentence(p["text"]))
        if one_line(p.get("conditions")):
            line += " **When:** %s" % sentence(p["conditions"])
        line += support(p, n, client)
        if one_line(p.get("comment")):
            line += " *Note: %s*" % sentence(p["comment"])
        lines.append(line)
    for x in r.get("client_exceptions") or []:
        line = "- **For client %s%s%s:** %s" % (CODE, one_line(x["client_ref"]), CODE, sentence(x["text"]))
        if one_line(x.get("conditions")):
            line += " **When:** %s" % sentence(x["conditions"])
        s, m = x.get("support_matters"), x.get("client_matters")
        if isinstance(s, int) and s > 0 and isinstance(m, int) and m > 0:
            line += " (seen in %d of their %d past engagements)" % (s, m)
        if one_line(x.get("comment")):
            line += " *Note: %s*" % sentence(x["comment"])
        lines.append(line)
    if r.get("all_services") is True:
        lines.append("- **For:** all of the client's work, not only this kind of work.")
    if one_line(r.get("replaces")):
        lines.append("- **Replaces the team's rule:** %s" % sentence(r["replaces"]))
    if years_text(r.get("tax_years")):
        lines.append("- **Tax years:** %s." % years_text(r["tax_years"]))
    if one_line(r.get("escalation")):
        lines.append("- **Escalate:** %s" % sentence(r["escalation"]))
    return lines + [""]


def has_exceptions(rules):
    return any(r.get("client_exceptions") for r in rules)


def note_lines(f, rules):
    """The note on client positions: a client file's own note, else the one for client exceptions when there are any."""
    if "client_ref" in f:
        return [client_note(f["client_ref"]), ""]
    return [CLIENT_NOTE, ""] if has_exceptions(rules) else []


def workflow_md(f, groups, linked):
    """The steps of the work in order, each with its rules' activity, and the paths where the work branches."""
    w = f.get("workflow")
    if not w or not w.get("steps"):
        return []
    steps, edges = w["steps"], w.get("edges") or []
    lead = "Do the work in this order, following the paths below where it branches." if edges else "Do the work in this order."
    lines = ["## Workflow", "", lead, ""]
    for i, st in enumerate(steps):
        line = "%d. **%s**" % (i + 1, one_line(st["name"]))
        line += ": " + sentence(st.get("description")) if one_line(st.get("description")) else "."
        act = st["activity_type"]
        if act in groups:
            line += (" Rules: [%s%s%s](activities/%s.md)" % (CODE, act, CODE, act)) if linked else (" Rules: %s%s%s" % (CODE, act, CODE))
        lines.append(line)
    lines.append("")
    if edges:
        node = lambda v: "Start" if v == "start" else "End" if v == "end" else one_line(steps[v]["name"])
        lines += ["Paths:", ""]
        for e in edges:
            line = "- %s -> %s" % (node(e["from"]), node(e["to"]))
            if e.get("outcome") in OUTCOME:
                line += ", after a person %s" % OUTCOME[e["outcome"]]
            if one_line(e.get("label")):
                line += ": " + sentence(e["label"])
            lines.append(line)
        lines.append("")
    return lines


def red_lines(f):
    out = []
    for r in f["rules"]:
        for p in r["positions"]:
            if p["tier"] == "unacceptable":
                line = "- %s (%s)" % (sentence(p["text"]), one_line(r["topic"]))
                if one_line(p.get("conditions")):
                    line += " **When:** %s" % sentence(p["conditions"])
                out.append(line)
    return out


def escalations(f):
    return ["- **%s:** %s" % (one_line(r["topic"]), sentence(r["escalation"])) for r in f["rules"] if one_line(r.get("escalation"))]


HOW_TO_USE = (
    "Follow the preferred position. Use a fallback only when its condition holds, and say which one you "
    "used and why. Never take a red-line position. When no position fits, or two rules conflict, say so "
    "and ask instead of guessing."
)


def footer(fp):
    return [
        "---",
        "",
        "Generated by %s from the team's reviewed playbook.json (rules fingerprint %s%s%s). "
        "Do not edit by hand: change playbook.json, run the check, and export again." % (GENERATOR, CODE, fp[:12], CODE),
        "",
    ]


def skill_md(f, name, groups, fp):
    n = f["precedent_count"]
    lines = [
        "---",
        "name: %s" % name,
        "description: %s" % json.dumps(description(f, groups)),
        "metadata:",
        "  generated-by: %s" % json.dumps(GENERATOR + " " + str(f.get("skill_version", ""))),
        "  rules-sha256: %s" % json.dumps(fp),
        "---",
        "",
        "# %s" % one_line(f["title"]),
        "",
    ]
    if one_line(f.get("general_guidance")):
        lines += [one_line(f["general_guidance"]), ""]
    if "client_ref" in f:
        lines += ["These rules come from the client's own documents and the team's past work for it, and were reviewed by the team. " + HOW_TO_USE, ""]
    else:
        lines += ["These rules come from the team's past work and were reviewed by the team. " + HOW_TO_USE, ""]
    lines += note_lines(f, f["rules"])
    rl = red_lines(f)
    if rl:
        lines += ["## Red lines (never)", ""] + rl + [""]
    esc = escalations(f)
    if esc:
        lines += ["## Escalate", ""] + esc + [""]
    lines += workflow_md(f, groups, True)
    lines += [
        "## Activities",
        "",
        "Before you do one of these parts of the work, read its file. It has the positions, their conditions and how often the team took them.",
        "",
        "| Activity | Rules | File |",
        "|---|---|---|",
    ]
    for act, rules in groups.items():
        topics = "; ".join(one_line(r["topic"]).replace("|", "/") for _, r in rules)
        lines.append("| %s%s%s | %s | [activities/%s.md](activities/%s.md) |" % (CODE, act, CODE, topics, act, act))
    lines.append("")
    return "\n".join(lines + footer(fp))


def activity_md(f, act, rules, fp):
    lines = ["# %s%s%s" % (CODE, act, CODE), "", "Part of: %s. %s" % (one_line(f["title"]), HOW_TO_USE), ""]
    lines += note_lines(f, [r for _, r in rules])
    for _, r in rules:
        lines += rule_md(r, f["precedent_count"], "##", "client_ref" in f)
    return "\n".join(lines + footer(fp))


def playbook_md(f, groups, fp):
    lines = ["# %s" % one_line(f["title"]), ""]
    if one_line(f.get("general_guidance")):
        lines += [one_line(f["general_guidance"]), ""]
    if "client_ref" in f:
        lines += ["These are the team's rules for this client, drafted from the client's own documents and past work and reviewed by the team. " + HOW_TO_USE, ""]
    else:
        lines += ["These are the team's rules for this work, drafted from its past work and reviewed by the team. " + HOW_TO_USE, ""]
    lines += note_lines(f, f["rules"])
    rl = red_lines(f)
    if rl:
        lines += ["## Red lines (never)", ""] + rl + [""]
    esc = escalations(f)
    if esc:
        lines += ["## Escalate", ""] + esc + [""]
    lines += workflow_md(f, groups, False)
    for act, rules in groups.items():
        lines += ["## %s%s%s" % (CODE, act, CODE), ""]
        for _, r in rules:
            lines += rule_md(r, f["precedent_count"], "###", "client_ref" in f)
    return "\n".join(lines + footer(fp))


def write(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def main(argv):
    args = argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__.strip().splitlines()[2])
        return 2
    opts = {"--out": "playbook-export", "--name": None, "--redact": None}
    rest = args[1:]
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
    names, cents = check_playbook.load_redactions(opts["--redact"]) if opts["--redact"] else ([], set())
    findings = check_playbook.check(f, names, cents)
    if findings:
        for code, path in findings:
            print("FAIL %s %s" % (code, path))
        print("%d finding(s). Nothing written. Fix playbook.json and run check_playbook.py." % len(findings))
        return 1
    name = opts["--name"] or slug(f["title"])
    if len(name) > 64 or not NAME.match(name):
        print("FAIL NAME --name must be lowercase letters, digits and single hyphens, at most 64 characters")
        return 2
    skill_dir = os.path.join(opts["--out"], name)
    existing = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_dir):
        try:
            with open(existing, encoding="utf-8") as fh:
                ours = ("generated-by: \"%s " % GENERATOR) in fh.read()
        except OSError:
            ours = False
        if not ours:
            print("FAIL OUT_EXISTS %s exists and was not written by this script; choose another --out or --name" % skill_dir)
            return 1
        shutil.rmtree(skill_dir)
    groups = activities(f["rules"])
    fp = check_playbook.fingerprint(f["rules"])
    os.makedirs(os.path.join(skill_dir, "activities"))
    write(existing, skill_md(f, name, groups, fp))
    for act, rules in groups.items():
        write(os.path.join(skill_dir, "activities", act + ".md"), activity_md(f, act, rules, fp))
    write(os.path.join(opts["--out"], "PLAYBOOK.md"), playbook_md(f, groups, fp))
    print("OK: wrote %s/ (%d activities) and %s" % (skill_dir, len(groups), os.path.join(opts["--out"], "PLAYBOOK.md")))
    if not opts["--redact"]:
        print("WARN no --redact list: client names and amounts were not checked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
