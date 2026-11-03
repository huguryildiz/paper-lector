# Scoring checklist

Score each run from its transcript and files. Each item is pass, fail or not applicable, with the line or file that shows it. The verdict item (N5) is the primary outcome; the rest say whether the mode was followed.

## Novelty check (scenarios A, B, C)

| Id | Passes when |
| --- | --- |
| N1 | The claim, full blocker, partial blockers and a prediction are written before the first query or count preview. |
| N2 | Every generated query and the assumed mapping are shown before they run, unless the run prompt delegated running them. The queries cover at least their words, the application, the abstract problem and one method-side neighbour. |
| N3 | Each query's count, records written and records screened are reported; any limit (200 keyless, 50 semantic, `--max`) is named. When `search_overlap.py` prints a cut line, the report says so before blaming missing words. |
| N4 | Every closest paper has a reading level. Nothing is said about a paper beyond its reading level. A closed paper is listed with title and DOI for the user, not treated as absent. |
| N5 | The verdict equals the expected verdict in [scenarios.md](scenarios.md). A Killed verdict names the decisive passage with its page. |
| N6 | The novelty type equals the expected type (Undetermined where scenarios.md says so). No score or percentage. |
| N7 | No "first", "no one has done this" or "novel" without scope; absence is written as "not found in the records screened". |
| N8 | Cleanup deletes only what the run downloaded. In frozen runs the evidence record holds the version read, SHA-256 of each PDF read, the decisive quote with page and the retrieval date. |

## Position (scenario D)

| Id | Passes when |
| --- | --- |
| P1 | One contribution sentence with its condition, result and comparator. |
| P2 | The table has a result row (bound, guarantee, counterexample, evidence or validity range) where the closest paper differs, and its assumption rows show the shared assumptions as the same. |
| P3 | The closest paper is discussed in the paragraph for that result row, not for an assumption it shares. |
| P4 | Every citation is audited (DOI, authors, year, venue, page seen); unverified items are listed; no work outside the given corpus is added. |
| P5 | No gap statement beyond the corpus; "original" is not claimed. |
