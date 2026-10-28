"""Tests for the skill's export script (skills/playbook-builder/scripts/export_playbook.py).

Runs the real script with `python -I` (isolated: it must find check_playbook.py next to itself) on the
fictional example, in a temp dir.
"""
import copy
import json
import pathlib
import re
import subprocess
import sys

SKILL = pathlib.Path(__file__).resolve().parents[2] / "skills" / "playbook-builder"
SCRIPT = SKILL / "scripts" / "export_playbook.py"
EXAMPLE = json.loads((SKILL / "assets" / "example-playbook.json").read_text())
NAME = "individual-return-preparation"


def run(tmp_path, playbook, *args):
    path = tmp_path / "playbook.json"
    path.write_text(json.dumps(playbook))
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(path), "--out", str(tmp_path / "out"), *args],
        capture_output=True, text=True, cwd=tmp_path,
    )


def frontmatter(md):
    front = re.match(r"^---\n(.*?)\n---\n", md, re.S).group(1)
    return {k: v for k, v in re.findall(r"^ *([a-z0-9-]+): (.*)$", front, re.M)}


def test_writes_a_skill_and_playbook_md(tmp_path):
    r = run(tmp_path, EXAMPLE)
    assert r.returncode == 0, r.stdout
    out = tmp_path / "out"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "PLAYBOOK.md",
        NAME + "/SKILL.md",
        NAME + "/activities/deductions.charitable.md",
        NAME + "/activities/deductions.home_office.md",
    ]
    md = (out / NAME / "SKILL.md").read_text()
    front = frontmatter(md)
    assert front["name"] == NAME  # matches the folder, as the Agent Skills spec requires
    desc = json.loads(front["description"])
    assert 0 < len(desc) <= 1024 and "Home office deduction method" in desc
    assert json.loads(front["rules-sha256"]) == EXAMPLE["local_test"]["content_sha256"]
    # Red lines and escalations are in SKILL.md itself; the activity files hold every position.
    red = md.split("## Red lines (never)")[1].split("##")[0]
    assert "Claim a home office for a space that is also used for personal purposes." in red
    assert "Escalate to the reviewing partner" in md
    for link in re.findall(r"\]\(([^)]+)\)", md):
        assert (out / NAME / link).is_file()
    everything = (out / "PLAYBOOK.md").read_text()
    for rule in EXAMPLE["rules"]:
        activity = (out / NAME / "activities" / (rule["activity_type"] + ".md")).read_text()
        for p in rule["positions"]:
            assert p["text"] in activity and p["text"] in everything
            if p["conditions"]:
                assert p["conditions"] in activity
    assert "(seen in 3 of 4 past matters)" in everything


def test_refuses_and_writes_nothing_on_a_finding(tmp_path):
    f = copy.deepcopy(EXAMPLE)
    f["rules"][0]["positions"][0]["text"] = "Email the client at jane@client-mail.invalid first."
    r = run(tmp_path, f)
    assert r.returncode == 1
    assert "FAIL NON_FICTIONAL_EMAIL rules.0.positions.0.text" in r.stdout
    assert "client-mail" not in r.stdout  # paths and codes only, never the text
    assert not (tmp_path / "out").exists()


def test_redact_list_is_checked(tmp_path):
    redact = tmp_path / "redact.txt"
    redact.write_text("reviewing partner\n")
    r = run(tmp_path, EXAMPLE, "--redact", str(redact))
    assert r.returncode == 1 and "LEAK_CLIENT_NAME rules.0.escalation" in r.stdout


def test_name_option_and_rerun_replace_its_own_output(tmp_path):
    assert run(tmp_path, EXAMPLE, "--name", "tax-prep").returncode == 0
    stale = tmp_path / "out" / "tax-prep" / "activities" / "old.activity.md"
    stale.write_text("from an earlier export")
    assert run(tmp_path, EXAMPLE, "--name", "tax-prep").returncode == 0
    assert not stale.exists()
    assert run(tmp_path, EXAMPLE, "--name", "Tax Prep").returncode == 2


def test_never_overwrites_a_folder_it_did_not_write(tmp_path):
    mine = tmp_path / "out" / NAME
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("---\nname: someone-elses\n---\n")
    r = run(tmp_path, EXAMPLE)
    assert r.returncode == 1 and "OUT_EXISTS" in r.stdout
    assert (mine / "SKILL.md").read_text().startswith("---\nname: someone-elses")
