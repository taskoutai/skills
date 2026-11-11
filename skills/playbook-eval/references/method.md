# How the playbook eval works

## The question

The firm already has skills. A playbook adds the team's positions, red lines and when to ask. The eval answers:
with the same skills, the same task and the same engagements, does adding the playbook make the agent's work match
what the team does more often? And between two versions of a playbook, is the new one better?

## The arms

An arm is a set of skills. Arms differ only in the playbook skill: the firm's skills, the task, the model, the turn
limit and the tools are the same. Each run is headless Claude Code in a fresh temporary folder with:

- `documents/`: a copy of the engagement's inputs. The deliverables are never copied.
- `out/`: where the agent writes its work.
- the arm's skills, loaded with `--plugin-dir` under one plugin name in every arm, so a skill's name never tells
  the agent which arm it is in.

`--setting-sources project` and `--strict-mcp-config` keep out the person's own skills, plugins, settings and MCP
servers (the taskout connector included); the run folder has no CLAUDE.md. Claude Code's start message lists what
it loaded: a run whose plugin skills aren't exactly the arm's, or that loaded any MCP server, fails and is not
judged. Firm skills are copied without the taskout block that taskout's bind script appends (that block sends the
agent to the connector); the playbook skill is copied as exported. Arms run in a different order per engagement.

## The answer key

What the team did on each engagement, rule by rule: whether the work touched the rule's subject, and which
position it took. Claude reads the deliverables only (never an arm's work), then a person confirms or corrects
every reading. A filed return or a sent deliverable is what the team did, not proof it was right; the eval
measures agreement with the team, which is what a playbook is for.

## The scores

- **Correct application** per engagement: of the rules the team's work touched, the share where the arm's work
  took the same position (not touching the rule counts as wrong). Claude reads each arm's work on its own, without
  the arm's name or the deliverables. Per arm: the mean over engagements with a 95% t interval.
- **The difference with the baseline** is paired: per engagement, the arm's score minus the baseline's, then the
  mean and its 95% interval. "Better" or "worse" only when the interval leaves out zero and at least 5 engagements
  are paired; otherwise "about the same" or "too few".
- **Closer to what the team sent**: Claude reads the deliverables and both arms' work as Work 1 and Work 2 and
  picks the closer one or a tie, twice with the order swapped. A preference counts only when both orders agree;
  otherwise it is a tie. Win rate of the decided ones with a Wilson interval.
- **Red lines taken**: positions the rubric marks as red lines that the arm's work took.
- **Asked where the team asked**: rules where the team's work shows someone was asked, and whether the arm asked.
- **Playbook skill used**: runs where the agent invoked the playbook skill. Claude Code decides from the skill's
  description; if it rarely does, the playbook arm is closer to skills-only than it looks.

## What it can't tell you

- With few engagements the intervals are wide; five is the least that can show a difference.
- The judge is a model. The answer key is confirmed by a person; the arms' readings and the preferences are not.
  Spot-check a few against the work.
- Engagements the playbook was built from would flatter it. The scripts can't tell which those were; the person
  can.
- Comparing two versions with one rubric measures both by that rubric's rules. A rule only in the older version
  isn't scored.
- An agent that can't ask a person here writes its questions to `out/questions.md`. Live, taskout's connector
  answers them; here, asking is scored, the answer isn't.
