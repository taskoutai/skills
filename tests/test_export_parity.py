"""The skill's export_playbook.py writes exactly what taskout's export (src/playbook/agent_export.ts, local
mode) writes, so a team gets the same files from either. The golden files are rendered by the TypeScript
side (npm run build:skill); this runs the real script with `python -I` on the same fictional playbooks.
"""
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "skills" / "playbook-builder" / "scripts" / "export_playbook.py"
GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", sorted(p.name for p in GOLDEN.iterdir() if p.is_dir()))
def test_script_matches_taskout_export(tmp_path, name):
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(GOLDEN / name / "playbook.json"), "--out", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout
    want = files(GOLDEN / name / "out")
    got = files(tmp_path / "out")
    assert sorted(got) == sorted(want)
    for path in want:
        assert got[path] == want[path], path


def test_both_fixtures_are_present():
    assert {p.name for p in GOLDEN.iterdir() if p.is_dir()} >= {"example", "edge"}
