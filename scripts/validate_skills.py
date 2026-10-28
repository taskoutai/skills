#!/usr/bin/env python3
"""Validate every skill in skills/ against the Agent Skills format and this repo's rules.

Usage: python3 scripts/validate_skills.py
Checks per skill: SKILL.md exists; frontmatter name matches the folder and the name format;
description 1-1024 characters; compatibility at most 500; SKILL.md under 500 lines; every relative
link in its markdown files resolves inside the skill; the README's skills table lists it.
Exit 0 = passed, 1 = findings. Standard library only.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def frontmatter(md):
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    if not m:
        return None
    return dict(re.findall(r"^([a-z0-9-]+): ?(.*)$", m.group(1), re.M))


def unquote(v):
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def check_skill(d, readme):
    out = []
    md_path = d / "SKILL.md"
    if not md_path.is_file():
        return ["%s: no SKILL.md" % d.name]
    md = md_path.read_text(encoding="utf-8")
    front = frontmatter(md)
    if front is None:
        return ["%s: SKILL.md has no frontmatter" % d.name]
    name = unquote(front.get("name", ""))
    if name != d.name:
        out.append("%s: frontmatter name %r does not match the folder" % (d.name, name))
    if len(name) > 64 or not NAME.match(name):
        out.append("%s: name must be lowercase letters, digits and single hyphens, at most 64" % d.name)
    desc = unquote(front.get("description", ""))
    if not 1 <= len(desc) <= 1024:
        out.append("%s: description must be 1-1024 characters (is %d)" % (d.name, len(desc)))
    if len(unquote(front.get("compatibility", ""))) > 500:
        out.append("%s: compatibility over 500 characters" % d.name)
    if md.count("\n") >= 500:
        out.append("%s: SKILL.md is 500 lines or more; move detail into references/" % d.name)
    for f in d.rglob("*.md"):
        text = f.read_text(encoding="utf-8")
        for link in LINK.findall(text):
            if re.match(r"^[a-z]+:", link):
                continue
            target = (f.parent / link).resolve()
            if not target.exists() or d.resolve() not in target.parents:
                out.append("%s: broken or outside link %s" % (f.relative_to(ROOT), link))
    if not re.search(r"^\| *%s *\|" % re.escape(d.name), readme, re.M):
        out.append("%s: not listed in the README's skills table" % d.name)
    return out


def main():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skills = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    if not skills:
        print("FAIL no skills in skills/")
        return 1
    findings = [f for d in skills for f in check_skill(d, readme)]
    for f in findings:
        print("FAIL " + f)
    if findings:
        return 1
    print("OK: %d skill(s): %s" % (len(skills), ", ".join(d.name for d in skills)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
