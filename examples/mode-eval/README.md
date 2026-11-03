# Mode evaluation

Four claims whose correct outcome a person already knows, used to check whether `novelty-check` and `position` reach it. The unit tests check the scripts; this set checks the decisions the modes lead an agent to.

Four scenarios find gross failures. They do not estimate how often the modes are right; that needs a larger labelled set.

## Files

- [scenarios.md](scenarios.md): scenarios A to C (novelty check): the claims, what the agent is given, and the expected outcomes, set by the person who read the decisive papers before any run.
- [scenario-d.md](scenario-d.md): scenario D (position), open until a candidate is chosen.
- [checklist.md](checklist.md): the scoring items.
- `FROZEN.sha256`: the hash of each scenario file once its expected outcomes are approved. A run whose scenario file no longer matches its hash does not count.
- `runs/<scenario>-<date>/`: one folder per run (gitignored under `runs/`): the transcript export, the report and the score sheet.

## Running one scenario

1. Check the freeze before each run: `shasum -a 256 -c FROZEN.sha256`. A scenario file is added with `shasum -a 256 <file> >> FROZEN.sha256` only after its expected outcomes are approved.
2. Make a new empty folder outside every project, and start a new agent session there. The mode searches the project for earlier novelty notes, so a run inside a project would find the answer.
3. Paste only the scenario's "Prompt" block. Do not give the decisive paper, the expected outcome or this folder.
4. Answer the agent's questions as the scenario's "If asked" line says. Supply only the PDFs listed there.
5. Save the transcript and the report in `runs/<scenario>-<date>/`. This folder sits inside the skill, so search the transcript for `mode-eval`: a run that read it does not count.

## Scoring

1. The person who set the expected outcome scores N5 (the verdict) or P2 to P3 for scenario D, from the report.
2. Two reviewer models score the whole checklist independently from the transcript, each item with the line that shows it. Their agreement is not evidence; it only flags items for the person to look at.
3. The person settles every item where the models disagree or either one fails it.

A scenario passes when its primary item (N5, or P2 and P3 for D) passes. Report the four results with the failed checklist items; do not combine them into one score.
