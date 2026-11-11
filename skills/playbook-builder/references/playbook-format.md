# playbook.json

One JSON object. Strict: unknown fields are refused. Schema: [../assets/playbook.schema.json](../assets/playbook.schema.json).

| Field | Rules |
|---|---|
| `format` | `"taskout.playbook"` |
| `format_version` | `"2"` |
| `skill_version` | `"1.5.0"` (this skill's version) |
| `title` | 2-200 characters: the kind of work in the team's words |
| `general_guidance` | Up to 4000 characters: 2-4 sentences on perspective, how the playbook was derived, what varied across engagements |
| `client_ref` | Client mode only ([client-mode.md](client-mode.md)): the firm's own reference for the client whose rules these are, 1-60 letters, digits, `._:-`. Never a name or a tax identifier |
| `task_id` | Client file only, optional: the service the rules are for, the id in `references/task.md`. Without it, the person importing chooses the service |
| `precedent_count` | Number of build engagements (not counting kept-back ones), 1-200; in a client file that client's, 0-200 |
| `firm_skills` | Optional, up to 20: the team's own skills the rules were compared with, `{name, sha256}` from `check_playbook.py --hash-skill`. Never their text |
| `rules` | 1-60 topics, in workflow order |
| `workflow` | Optional: the steps of the work, in order (below). Not in a client file |
| `rules[].topic` | 2-200 characters |
| `rules[].activity_type` | Lowercase dotted, e.g. `review.income_sources` |
| `rules[].guidance` | Up to 2000 characters for the reviewer (optional) |
| `rules[].escalation` | Up to 1000 characters: who to escalate to, and when, e.g. "the tax partner, when support is below substantial authority" (optional) |
| `rules[].positions` | 1-6 positions; at most one `preferred` |
| `rules[].tax_years` | Optional: the tax years the rule holds for, `2025`, `2023-2025`, `2026-` (from) or `-2024` (up to); empty = every year |
| `rules[].all_services` | Client file only, optional: `true` when the rule holds for all of the client's work, not only this service |
| `rules[].replaces` | Client file only, optional: the topic of the service playbook's rule this client rule replaces, exactly as it is written there |
| `rules[].stated_vs_practice` | With `firm_skills`, required on every topic: `agree` or `conflict` (each needs a position with `stated_refs` and one with `support_matters` above 0), `stated_only` (`stated_refs`, no engagement support), `practice_only` (no `stated_refs`). Without `firm_skills`, leave it out |
| `positions[].tier` | `preferred`, `fallback` or `unacceptable` |
| `positions[].text` | 3-3000 characters: the position in business terms, with its parameters |
| `positions[].conditions` | Up to 1000 characters: when this position applies (required in practice for a fallback) |
| `positions[].comment` | Up to 1000 characters (optional): e.g. why an outlier was kept |
| `positions[].support_matters` | Distinct build engagements that show it, 0 to `precedent_count` |
| `positions[].citation_refs` | Up to 30 ids from your report (`c12`), letters, digits, `._-` only. Never file names |
| `positions[].stated_refs` | Up to 30 ids from your report (`s3`) for the passages of the team's skills that state this position. Only with `firm_skills` |
| `positions[].doc_refs` | Client file only: up to 30 ids from your report (`d2`) for the passages of the client's own documents that state this position. In a client file every position needs `doc_refs` or `support_matters` above 0 |
| `rules[].client_exceptions` | Optional, up to 30: where one client's own engagements keep doing this differently (below). Not in a client file |
| `local_test` | Optional: the test from step 10 (below) |

## client_exceptions

One per client per topic. It replaces the topic's positions for that client only; red lines still apply.

| Field | Rules |
|---|---|
| `client_ref` | The firm's own client reference, 1-60 letters, digits, `._:-`. Never a name or a tax identifier |
| `text` | 3-3000 characters: that client's position, in business terms |
| `conditions` | Up to 1000 characters (optional) |
| `comment` | Up to 1000 characters (optional) |
| `support_matters` | That client's build engagements that show it, at least 1 (2 or more to call it the client's practice) |
| `client_matters` | All of that client's build engagements, at least `support_matters` |
| `citation_refs` | Up to 30 ids from your report, as for positions |

## workflow

| Field | Rules |
|---|---|
| `steps` | 1-40 steps, in the order the work happens: the activities the user confirmed |
| `steps[].activity_type` | The step's activity type: the rules with this `activity_type` belong to it. Once per step |
| `steps[].name` | 3-80 characters, in the team's words |
| `steps[].description` | Up to 600 characters (optional) |
| `edges` | Optional, up to 200: how the steps connect. Without edges the steps run in order |
| `edges[].from` | A step's index in `steps` (0 = first), or `"start"` |
| `edges[].to` | A step's index, or `"end"` |
| `edges[].label` | Up to 120 characters: the condition for this path (optional) |
| `edges[].outcome` | Optional: `approve`, `reject` or `answer`, the path after a person decides an agent's question at that step |

## local_test

| Field | Rules |
|---|---|
| `content_sha256` | The rules' fingerprint from `check_playbook.py --fingerprint`, taken after the last change to any rule |
| `held_out_matters` | How many kept-back engagements were tested, 1-50 |
| `readings_confirmed` | `true`: the user confirmed each reading of what the team did |
| `results` | One entry per kept-back engagement and rule it touches: `{rule, matter, predicted, actual}` |
| `results[].rule` | The rule's index in `rules` (0 = first) |
| `results[].matter` | The engagement's number, 1 to `held_out_matters`. Never its name |
| `results[].predicted` | Index of the position the playbook applies, from the inputs only; `null` if none applies |
| `results[].actual` | Index of the position the team's deliverables took; `null` if none of them |
