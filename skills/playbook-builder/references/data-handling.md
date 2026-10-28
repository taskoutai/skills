# Data handling

What goes where when you use this skill:

| Stays on this machine | Leaves it only if the user shares it |
|---|---|
| The matters' documents and deliverables | `playbook.json`, and `playbook-export/` made from it |
| `.playbook-builder/report.md` (citations: files, pages, cells) | Opaque citation ids (`c12`), not what they point to (in `playbook.json` only) |
| `.playbook-builder/redact.txt` (names, identifiers, amounts) | Support counts per position |
| `.playbook-builder/notes.md` | The test: per rule and matter number, the predicted and the actual position (in `playbook.json` only) |

- The model this agent runs on reads the documents in this session. That is between the team and its
  model provider. If the work involves taxpayer data (IRC 7216) or other regulated data, the team
  decides whether this use is permitted and what consent it needs.
- The export holds only the rules' text, so it is as safe to share as `playbook.json` after the
  check passes. Any AI tool the team gives it to will read those rules; that is the point of it.
- If the team imports into taskout: taskout checks the uploaded file for real-looking identifiers, placeholder tokens and text that
  reads like instructions, and refuses the whole file on any hit. It can't check for the client's own
  names and amounts, because it never sees the documents: the `redact.txt` check in
  `scripts/check_playbook.py` is the only check that can.
- In taskout every imported rule and position is a model proposal until a person approves it. Using
  the playbook for synthetic data, evals or with Claude in taskout needs a separate approval by a team
  admin.
- taskout can't open the citations behind an imported position. To check a position, open
  `report.md` here.
