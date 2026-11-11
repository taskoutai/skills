# taskout skills

[Agent Skills](https://agentskills.io) for capturing how a team does its work and giving it to the team's AI agents. Everything runs on your machine: your documents are read by the agent you already use and are never uploaded anywhere by these skills.

## Skills

| Skill | Useful for |
|-------|------------|
| playbook-builder | Turning a team's past work (one folder per past job), or one client's documents and past engagements, into a playbook of reviewed rules: preferred positions, accepted fallbacks and when they apply, red lines, when to escalate. Tests the rules on jobs kept back, then exports them as a skill your agents follow and a `PLAYBOOK.md` for any AI model. |
| playbook-eval | Checking a playbook actually changes the work: your agent runs the same kept-back jobs with your own skills only and with your skills plus the playbook (or two playbook versions), and each run is scored against what your team actually sent. Uses your own Claude key. |
| judge-builder | For playbooks kept in taskout: tuning an automated judge (with GEPA) until it agrees with your reviewers, judging every finished job with it, and turning the jobs that went wrong into proposed rule changes. Uses your own Claude key. |

## Installing

### Claude Code

```
/plugin marketplace add taskoutai/skills
/plugin install taskout@taskout
```

### Codex

```sh
codex plugin marketplace add taskoutai/skills
codex plugin add taskout@taskout
```

### npx skills

```
npx skills add https://github.com/taskoutai/skills
```

### Clone / copy

Clone this repo and copy the skill folders from `skills/` into your agent's skills directory:

| Agent | Skill directory |
|-------|-----------------|
| Claude Code | `~/.claude/skills/` (or `.claude/skills/` in a project) |
| Cursor | `~/.cursor/skills/` |
| OpenCode | `~/.config/opencode/skills/` |
| OpenAI Codex | `~/.codex/skills/` |

Start a new session after installing.

## Using playbook-builder

1. Put the past work for **one** kind of job in a folder, one subfolder per job, for example `<job>/documents/` (what came in) and `<job>/deliverables/` (what the team produced).
2. Ask your agent: *"Use the playbook-builder skill to build a playbook for our <kind of work> from the past matters in `<folder>`."*
3. The agent outlines the work and stops for you to confirm the activities, drafts the rules, scrubs client details, reviews the rules with you, and tests them on jobs you kept back.
4. It exports `playbook-export/<name>/`, a skill for your team's agents: copy it into `.claude/skills/` in your repo (or any agent's skills folder). `playbook-export/PLAYBOOK.md` is the same rules in one file for any other AI tool: paste it into custom instructions or add it as `AGENTS.md`.

What stays on your machine: the documents, and a `.playbook-builder/` working folder with the citations behind each rule and the redaction list. What you can share: `playbook.json` and its export, after the bundled check script passes. The check refuses real-looking identifiers, placeholder tokens, text that reads like instructions to a model, and every client name and amount on your redaction list.

playbook-builder's scripts (`check_playbook.py`, `export_playbook.py`) need Python 3.9+, use the standard library only and make no network calls.

## Using playbook-eval

1. Keep back past jobs the playbook wasn't built from (at least 5; 10 or more is better), one folder each with `documents/` and `deliverables/`, as text files.
2. Ask your agent: *"Use the playbook-eval skill to check whether our playbook in `playbook-export/<name>` improves on our own skills, on the jobs in `<folder>`."*
3. The agent tells you how many runs it needs and waits for your go-ahead, runs each arm in a clean folder, then shows you its reading of what your team did on each job for you to confirm before scoring anything.
4. You get `playbook-eval/report.md` (per arm: how often the agent took your team's position, red lines crossed, rules it still gets wrong, cost) and `playbook-eval/result.json` (counts only, nothing from the work).

Needs Claude Code, Python 3.10+, `pip install "anthropic>=2.6"` and your own `ANTHROPIC_API_KEY`. The documents and work go only to the Claude calls made with your key.

## Using judge-builder

judge-builder works with a playbook kept in taskout: it learns from your reviewers' verdicts, which you download from the playbook's **How it's working** tab. It needs Python 3.10+, `pip install "gepa==0.1.4" "anthropic>=2.6"` and your own `ANTHROPIC_API_KEY`. The work stays on your machine; only the judge's instructions, its verdicts and proposed rules go to taskout, and a person approves each.

## Optional: taskout

taskout can import `playbook.json`, keep the playbook current from new work and team conversations, version every change behind a person's approval, and measure how often people still correct the agent on each rule. None of that is needed for playbook-builder or playbook-eval.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
