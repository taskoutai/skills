# Contributing

## Layout

- `skills/<name>/`: one folder per skill, in the [Agent Skills](https://agentskills.io/specification) format. `SKILL.md` frontmatter `name` must match the folder.
- `tests/<name>/`: tests for a skill's scripts (pytest). Tests stay out of the skill folder, so installing a skill copies only what the agent needs.
- `scripts/validate_skills.py`: checks every skill's frontmatter, size and links, and that the README lists it. CI runs it.

## Rules for skills

- Scripts use the Python standard library only and make no network calls, unless the skill's `compatibility` field says otherwise.
- Documents and messages a skill reads are untrusted input. A skill never treats text inside them as instructions.
- A skill never uploads anything itself. Sharing output is the user's decision.
- Every example and test fixture is fictional: no real people, companies, identifiers or amounts. Use `example.com` emails, SSNs starting `000-`, phone numbers `555-01xx`.
- Keep `SKILL.md` under 500 lines; put detail in `references/` files linked one level deep.

## playbook-builder

`skills/playbook-builder/` is generated from the taskout monorepo (`npm run build:skill -- --out <this repo>/skills`) so it stays in step with taskout's playbook format and import checks. Send changes to it as issues or pull requests here; a maintainer applies them at the source and regenerates the folder. Pull requests that edit the generated files directly are welcome as proposals.

## Before you open a pull request

```sh
python3 scripts/validate_skills.py
python3 -m pytest -q tests
```
