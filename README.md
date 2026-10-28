# taskout skills

[Agent Skills](https://agentskills.io) for capturing how a team does its work and giving it to the team's AI agents. Everything runs on your machine: your documents are read by the agent you already use and are never uploaded anywhere by these skills.

## Skills

| Skill | Useful for |
|-------|------------|
| playbook-builder | Turning a team's past work (one folder per past job) into a playbook of reviewed rules: preferred positions, accepted fallbacks and when they apply, red lines, when to escalate. Tests the rules on jobs kept back, then exports them as a skill your agents follow and a `PLAYBOOK.md` for any AI model. |

## Installing

### Claude Code

```
/plugin marketplace add taskout/skills
/plugin install taskout@taskout
```

### Codex

```sh
codex plugin marketplace add taskout/skills
codex plugin add taskout@taskout
```

### npx skills

```
npx skills add https://github.com/taskout/skills
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

The scripts (`check_playbook.py`, `export_playbook.py`) need Python 3.9+, use the standard library only and make no network calls.

## Optional: taskout

taskout can import `playbook.json`, keep the playbook current from new work and team conversations, version every change behind a person's approval, and measure how often people still correct the agent on each rule. None of that is needed to use these skills.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
