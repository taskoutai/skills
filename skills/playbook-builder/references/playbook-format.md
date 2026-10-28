# playbook.json

One JSON object. Strict: unknown fields are refused. Schema: [../assets/playbook.schema.json](../assets/playbook.schema.json).

| Field | Rules |
|---|---|
| `format` | `"taskout.playbook"` |
| `format_version` | `"2"` |
| `skill_version` | `"1.2.0"` (this skill's version) |
| `title` | 2-200 characters: the kind of work in the team's words |
| `general_guidance` | Up to 4000 characters: 2-4 sentences on perspective, how the playbook was derived, what varied across matters |
| `precedent_count` | Number of build matters (not counting kept-back ones), 1-200 |
| `rules` | 1-60 topics, in workflow order |
| `rules[].topic` | 2-200 characters |
| `rules[].activity_type` | Lowercase dotted, e.g. `review.income_sources` |
| `rules[].guidance` | Up to 2000 characters for the reviewer (optional) |
| `rules[].escalation` | Up to 1000 characters: who to escalate to, and when (optional) |
| `rules[].positions` | 1-6 positions; at most one `preferred` |
| `positions[].tier` | `preferred`, `fallback` or `unacceptable` |
| `positions[].text` | 3-3000 characters: the position in business terms, with its parameters |
| `positions[].conditions` | Up to 1000 characters: when this position applies (required in practice for a fallback) |
| `positions[].comment` | Up to 1000 characters (optional): e.g. why an outlier was kept |
| `positions[].support_matters` | Distinct build matters that show it, 0 to `precedent_count` |
| `positions[].citation_refs` | Up to 30 ids from your report (`c12`), letters, digits, `._-` only. Never file names |
| `local_test` | Optional: the test from step 10 (below) |

## local_test

| Field | Rules |
|---|---|
| `content_sha256` | The rules' fingerprint from `check_playbook.py --fingerprint`, taken after the last change to any rule |
| `held_out_matters` | How many kept-back matters were tested, 1-50 |
| `readings_confirmed` | `true`: the user confirmed each reading of what the team did |
| `results` | One entry per kept-back matter and rule it touches: `{rule, matter, predicted, actual}` |
| `results[].rule` | The rule's index in `rules` (0 = first) |
| `results[].matter` | The matter's number, 1 to `held_out_matters`. Never its name |
| `results[].predicted` | Index of the position the playbook applies, from the inputs only; `null` if none applies |
| `results[].actual` | Index of the position the team's deliverables took; `null` if none of them |
