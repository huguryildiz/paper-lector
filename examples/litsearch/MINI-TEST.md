# $0 mini test, 2026-10-18

The working folder this test ran in (`examples/litsearch-eval/`: PDFs, scripts, frozen queries) was deleted after the write-up; the folder names below refer to it.

Local models only (`--provider local`, potion-science-32M and potion-retrieval-32M), no API calls for ranking. OpenAlex cost of building the survey set: about $0.02. Queries were written blind by a separate agent (survey abstract, or LitSearch question, as its only input) and frozen with SHA-256 before any PDF was ranked.

## Surveys (`surveys/`)

7 IEEE surveys in two groups. Each survey's references in the group pool are its gold, and the other surveys' references are the distractors. Up to 60 PDFs per survey, seeded draw. Pools: quantum 167 PDFs, wireless 194.

| Survey | Gold in pool | Gold in top 10 (science, fused) | Random expectation | AP | Random AP |
| --- | --- | --- | --- | --- | --- |
| UAV | 61/194 | 9 | 3.1 | 0.80 | 0.31 |
| Satellite | 34/194 | 9 | 1.8 | 0.58 | 0.18 |
| QKD networks | 81/167 | 8 | 4.9 | 0.75 | 0.49 |
| Entanglement-assisted quantum networks | 76/167 | 8 | 4.6 | 0.61 | 0.46 |
| Internet of Underwater Things | 40/194 | 7 | 2.1 | 0.54 | 0.21 |
| RIS | 60/194 | 6 | 3.1 | 0.42 | 0.31 |
| Quantum internet | 79/167 | 5 | 4.7 | 0.52 | 0.47 |

Mean over 7 questions: AP 0.60 (95% bootstrap 0.51 to 0.70) for science and 0.61 for retrieval, against 0.35 for a random order. The fused order (main + subject) is equal to or slightly better than main alone. Dropping pool papers published after the survey changes nothing. The quantum surveys share about half their references, so that group separates poorly; for quantum internet the result is no better than random.

## LitSearch on DEIXIS data (`deixis-ls/`)

20 questions from DEIXIS's seeded order. 19 were run; one lost its gold PDF. Collection: the gold paper plus the first arXiv or ACL papers of DEIXIS's pre-rerank list for the same question. Median 32 PDFs after failed downloads.

| Order | hit@3 | hit@10 | MRR |
| --- | --- | --- | --- |
| paper-lector local science, fused | 0.32 | 0.63 | 0.28 |
| paper-lector local retrieval, fused | 0.32 | 0.63 | 0.37 |
| paper-lector local retrieval, main only | 0.37 | 0.68 | 0.35 |
| DEIXIS rerank (voyage rerank-3-lite, abstracts), same papers | 0.58 | 0.63 | 0.48 |

On the 13 questions where DEIXIS's list holds the gold paper: DEIXIS rerank puts it in the top 3 in 11, paper-lector local in 4 or 5. MRR 0.69 against 0.27 to 0.36. retrieval beats science on MRR by 0.10 (95% interval −0.21 to −0.00, science minus retrieval), a borderline difference on 19 questions.

Caveat: the distractors are DEIXIS's own top candidates, so they are hard and on topic. The pilot (voyage, easier distractors) had MRR 0.93; that and this are not comparable.

### Voyage on the same 19 collections

`rank.py --provider voyage` (voyage-4-large, hybrid windows, rerank-3), with copies of the frozen queries holding only `main` and `subject` (`queries2/`, same text; per-query scores do not depend on the other queries, so fused ranks are unchanged by the cut). Tokens: 9.80M embedding, 4.51M rerank.

| Order | hit@3 | hit@5 | hit@10 | MRR |
| --- | --- | --- | --- | --- |
| paper-lector voyage, main only | **0.84** | **0.89** | **0.89** | **0.71** |
| paper-lector voyage, fused (main + subject) | 0.58 | 0.74 | 0.89 | 0.50 |
| DEIXIS rerank, same papers | 0.58 | 0.58 | 0.63 | 0.48 |
| paper-lector local retrieval, fused | 0.32 | 0.47 | 0.63 | 0.37 |

On the 13 questions where DEIXIS's list holds the gold paper: voyage main only puts it in the top 3 in 12, DEIXIS rerank in 11, voyage fused in 8, local in 4.

**The blind `subject` query hurts with voyage.** Main only against fused: MRR +0.21 (95% interval +0.08 to +0.36). Main alone is better in 10 questions and worse in none. With the local models the difference is −0.03 (no effect). LitSearch questions point at one specific paper, and a `subject` sentence written from the question alone is broader than the question, so fusing it pulls broader papers up. The pilot, whose `subject` was written with the gold titles in view, showed the opposite (+0.07), which fits that reading. On the surveys, whose questions are broad, fused and main were equal.

voyage fused against local retrieval fused: MRR +0.13 (−0.03 to +0.30). voyage fused against DEIXIS rerank: +0.02 (−0.22 to +0.27). Neither is beyond chance on 19 questions.

## What it says

- With voyage and the main question alone, paper-lector finds the single gold paper among DEIXIS's own top candidates in the top 3 in 16 of 19 questions. That is at least as good as DEIXIS's reranker on the same papers.
- The default fuse (main + subject) cost about 0.2 MRR here. That is a finding about the default, measured on 19 narrow questions: worth a larger check before changing `SKILL.md`, which recommends main + subject.
- The local models separate a survey's references from a neighbouring survey's clearly (AP 0.60 against 0.35), but on narrow questions they rank the gold paper far below voyage (MRR 0.37 against 0.71).

PDFs were deleted after the runs. `download.py` in each folder re-downloads them.

## Voyage main against fused on 27 more questions (n = 46)

The 19-question result needed a check before `SKILL.md` changes. `deixis-ls/build.py` was extended (same seeded rule, first 50 questions; the first 20 are unchanged). Questions 21 to 50 gave 27 usable ones: 3 lost their gold PDF. `subject` was written blind from the question by a fresh Sonnet agent (the original prompt file is not in the repo, so the prompt was rebuilt from the `SKILL.md` slot and keyword rules) and frozen in `frozen_queries2.json` before any PDF was ranked. Same voyage settings as above. Tokens for the 27: about 11.4M embedding, 6.1M rerank. Script: `deixis-ls/run_voyage2.sh`; metrics: `evaluate.py`.

| Set | n | MRR main only | MRR fused | main - fused (95% interval) | main better / worse |
| --- | --- | --- | --- | --- | --- |
| First 19 | 19 | 0.71 | 0.50 | +0.21 (+0.08 to +0.36) | 10 / 0 |
| Added | 27 | 0.65 | 0.58 | +0.07 (−0.04 to +0.17) | 12 / 4 |
| All | 46 | 0.67 | 0.55 | +0.12 (+0.04 to +0.21) | 22 / 4 |

hit@3 on all 46: main 0.80, fused 0.61, DEIXIS rerank 0.48. hit@10: 0.91, 0.89, 0.59.

Main only still wins, and the interval for all 46 stays above zero, but the effect on new data is a third of the first estimate and not beyond chance by itself. The first 19 were the questions on which the gap was noticed, so +0.21 was probably inflated. Splitting by LitSearch's `specificity` flag does not show a breadth dependence (+0.19 on 10 questions, +0.11 on 36), so there is no evidence here for a breadth rule. Not measured: broad, survey-like questions (the survey set showed fused and main equal there), and a `subject` written by the user instead of blind.

**Recommendation.** Keep the default (main + subject) in `SKILL.md`, and add one sentence: when the question points at one specific paper, main only ranked the gold paper higher in 22 of 46 questions and lower in 4 here; the other slots still get their own columns, so nothing is lost by reading them. A switch of the default needs a test on broad questions first. No edit to `SKILL.md` or `rank.py` was made.

PDFs deleted after the runs.

## Rebuilt set, 20 PDFs per question, voyage (2026-10-18)

The working folder above was deleted, so the set was rebuilt from DEIXIS's data in [`examples/litsearch-eval`](../litsearch-eval) (`build.py`, `subset.py`): the same first 50 seeded questions, gold plus the first 19 downloaded arXiv or ACL papers of DEIXIS's pre-rerank list, 20 PDFs per question (8 and 13 in two questions with short lists). 48 questions were usable; 2 lost their gold PDF. `main` is the LitSearch question as written, and `subject` was written again, blind, from the question alone by a fresh Sonnet agent, then frozen (`FROZEN.sha256`) before any ranking. `rank.py --ids subset20.csv`, voyage, hybrid only. Tokens: 10.2M embedding (more taken from the cache), 6.8M rerank. Metrics: `evaluate20.py`, `results20.json`.

| Order | hit@3 | hit@5 | hit@10 | MRR |
| --- | --- | --- | --- | --- |
| voyage, main only | 0.75 | 0.85 | 0.96 | 0.71 |
| voyage, fused (main + subject) | 0.75 | 0.88 | 0.96 | 0.72 |

Main only against fused: MRR −0.01 (95% interval −0.07 to +0.05); main better in 7 questions, worse in 7.

**The main-only gain did not come back.** With new blind `subject` queries, the two orders are equal. The earlier +0.12 on 46 questions came from one set of `subject` sentences and 40-PDF collections, and its out-of-sample part was already small (+0.07, interval crossing zero). The questions here are mostly the same ones, so this is not independent data on the questions; what changed is the `subject` text and the collection size. 20 PDFs make the task easier than 40, so these numbers are not comparable with the tables above; the comparison of main and fused within this table is. Read together, the evidence does not support recommending main only: how much `subject` helps or hurts depends on how it is written.
