# Method

The same method taskout uses when it builds a playbook from uploaded matters. Where it says "cite
evidence", cite with ids from your `report.md`.

## Pass 1: outline one matter

- You are outlining how an organization performs a kind of work (for example underwriting a property deal, reviewing a contract, preparing a return), from the documents of one historical matter. The outline is the backbone for the organization's general rules, which people and AI agents apply to new matters, so keep it GENERIC: the activities anyone doing this work at this organization performs, not a map of this matter's files.
- Include activities that leave only traces in documents: reviewing photos, researching comparables online, talking to contractors or estimating internally, checking sources. Name inputs and outputs by kind ("property photos", "online comparable sales", "contractor quote or internal estimate"), not by file name.
- 3-8 activities in the order they are normally done. No addresses, names or this matter's amounts in names or descriptions.
- Each activity: a lowercase dotted `activity_type` (for example `intake.document_check`), a short
  name, its order, a description, inputs and outputs by kind, and 1-8 citations that show it happened.

## Pass 2: rules for one confirmed activity

- The activity was confirmed by the user; their wording is authoritative.
- Write general, reusable rules: how this organization does the activity in any matter, with the parameters that define its practice (factors, rates, thresholds, minimums, rounding, ordering of checks, what must be documented). A good rule lets someone generate a new, different case and know the correct handling.
- Do not describe this matter: no addresses, names, or this matter's computed results (e.g. its ROI or spread). Inputs of this matter appear only if they are the organization's standing parameters. At most 4 rules; skip anything that is a one-off.
- Describe the practice, not the tool: no sheet names, column layouts, cell references or file-naming conventions (they are this matter's template, and an agent following them would copy the template, not the judgment). Cite cells as evidence, but state the rule in business terms ("repairs carry a contingency of 10% of the itemized subtotal").
- Formulas and worked calculations are the strongest evidence of a rule: trace them to their inputs.
- Do not repeat a rule already written for an earlier activity.

## Pass 3: combine rules into topics with positions

Each topic (a rule in the playbook file) gets 1-6 positions:

- preferred: what the organization does by default (exactly one per rule); fallback: a different position it has actually used INSTEAD of the preferred one, with the conditions under which it uses it; unacceptable: positions the evidence shows it avoids or rejects (only if the rules show this).
- A fallback replaces the preferred position; it never adds to it. Extra steps or items done on top of the default only in some situations (for example extra checklist items when a case has a particular feature) belong in the preferred position as "When <situation>, also <step>", citing the rules for both, or in a rule of their own. Do not label them fallback because fewer matters show them.
- State positions in business terms with their parameters (rates, factors, thresholds, rounding, order of checks). When matters used different values, make the most common one preferred and the others fallbacks with conditions if the rules suggest any.
- Keep matter-specific details out (addresses, names, one deal's results). general_guidance: 2-4 sentences on perspective, how the playbook was derived, and what varied across matters.
- Group by workflow activity with a lowercase dotted activity_type, unifying differently named equivalents.
- Every figure in a position must appear in a rule it combines (and so in a cited document).
- Do not write how many matters support a position in its text: that is `support_matters`.
