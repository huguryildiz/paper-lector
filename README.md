<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img src="assets/icon.svg" alt="paper-lector logo" width="120" height="120">
</p>

<h1 align="center">paper-lector</h1>

<p align="center">
  <strong>Agent Skill for Claude Code and Codex</strong><br>
  <sub>Ranks a PDF corpus against fixed research questions to prioritize reading, indicating where each paper should be read first, without establishing what it reports.</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python_3.12-0b1220?style=for-the-badge&logo=python&logoColor=3776AB" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Claude_Code_%C2%B7_Codex_Skill-0b1220?style=for-the-badge&logo=claude&logoColor=D97757" alt="Claude Code and Codex skill">
  <img src="https://img.shields.io/badge/OpenAlex-0b1220?style=for-the-badge&logo=openaccess&logoColor=F68212" alt="OpenAlex">
  <img src="https://img.shields.io/badge/Voyage_AI_%C2%B7_BM25-0b1220?style=for-the-badge&logo=databricks&logoColor=F2B544" alt="Voyage AI and BM25">
  <img src="https://img.shields.io/badge/pdftotext-0b1220?style=for-the-badge&logo=files&logoColor=EC1C24" alt="pdftotext">
  <img src="https://img.shields.io/badge/pytest-0b1220?style=for-the-badge&logo=pytest&logoColor=0A9EDC" alt="pytest">
</p>

<h3 align="center">
  <a href="#overview">Overview</a>
  &nbsp;·&nbsp;
  <a href="#install">Install</a>
  &nbsp;·&nbsp;
  <a href="#usage">Usage</a>
  &nbsp;·&nbsp;
  <a href="#example">Example</a>
  &nbsp;·&nbsp;
  <a href="#benchmarks">Benchmarks</a>
  &nbsp;·&nbsp;
  <a href="REFERENCE.md">Reference</a>
</h3>

---

## Overview

paper-lector is an agent skill for Claude Code and Codex with three scripts:

- `openalex_search.py` searches OpenAlex: keyword, semantic, citing works, references.
- `fetch_pdf.py` downloads open-access PDFs and lists the rest for manual download.
- `rank.py` ranks your own PDFs against a few frozen research-question queries and tells you which pages to read first.

It writes no answer, unlike PaperQA2 or NotebookLM: it gives a reading order and page ranges, which you check by reading. A high rank means the text resembles the question, not that the paper answers it. Every input and output stays a local file, with what a rerun needs (frozen queries, the SHA-256 of every PDF, versions). [`REFERENCE.md`](REFERENCE.md) has every option, output file and edge case.

## Install

macOS or Linux (on Windows, use WSL), Python 3.12 and `pdftotext` from poppler: `brew install python@3.12 poppler` on macOS, `sudo apt install python3.12 python3.12-venv poppler-utils` on Ubuntu 24.04.

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -c constraints.txt
mkdir -p ~/.claude/skills ~/.codex/skills
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector   # Claude Code
ln -s ~/Documents/GitHub/paper-lector ~/.codex/skills/paper-lector    # Codex
```

Put API keys in `~/.config/paper-lector/.env` (all projects) or a project's `.env`:

- `OPENALEX_API_KEY`, free and optional: [openalex.org/signup](https://openalex.org/signup). Without it, keyword and citing searches stop at the first 200 works and the daily budget is about 100 searches, shared by everyone on the same IP address.
- `VOYAGE_API_KEY` for ranking with the default provider: [dashboard.voyageai.com](https://dashboard.voyageai.com/organization/api-keys). Without a payment method the account gets low rate limits and may stop on HTTP 429. Without a key, rank with `--provider local`.

```bash
mkdir -p ~/.config/paper-lector
install -m 600 .env.example ~/.config/paper-lector/.env    # then fill in the keys
.venv/bin/python scripts/rank.py --setup                   # once, online; add --provider local without a Voyage key
```

## Usage

In Claude Code, type `/paper-lector` and the request; in Codex, mention `$paper-lector`. A plain request such as "has this been done?" also loads it. Name the mode, or let [`SKILL.md`](SKILL.md) pick one. Each mode works alone.

```text
/paper-lector novelty-check: a scheduler that knows each quantum memory's
remaining coherence time serves more requests than one that only knows link ages.
Try to kill this.
```

| Mode | For | Example request |
| --- | --- | --- |
| [`discover`](modes/discover.md) | Topics and contribution candidates | "I know MDPs and I'm moving into quantum networks. Which standard assumptions break there?" |
| [`novelty-check`](modes/novelty-check.md) | Trying to refute a claim against prior work; a scoped verdict and three axes (prior work, support, feasibility), no novelty score | "Has anyone shown X under Y? Try to kill it." |
| [`test`](modes/test.md) | A small pilot model, or what a result establishes | "My policy beats greedy by 12%. What is the simple explanation?" |
| [`position`](modes/position.md) | A positioning table and related-work section for a stated result | "Here is my result and the five closest PDFs. Write the related work." |
| [`search-rank`](modes/search-rank.md) | The scripts above | "Find and rank papers on scheduling entanglement among many users." |

Generated searches are shown before they run unless you say "search and run it yourself"; nothing paid starts without your approval. A search that finds nothing is a lead, and no mode concludes that an idea is original.

## Example

[`examples/entanglement-scheduling`](examples/entanglement-scheduling) is a complete run on this question:

> Which methods (optimization, heuristics, reinforcement learning) have been used to schedule entanglement distribution in a multi-user quantum network, and with which metrics were they compared?

From the shell, in a new empty folder:

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python
mkdir -p ~/research/entanglement-scheduling/queries && cd ~/research/entanglement-scheduling
git init -q                           # marks the project root
cp $PL/examples/entanglement-scheduling/literature.json .
cp $PL/examples/entanglement-scheduling/queries/queries.json queries/

$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --exact '("quantum network" OR "quantum networks" OR "quantum internet") AND (entangl*) AND (schedul*)'
$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --semantic 'Scheduling entanglement distribution among multiple users in a quantum network with optimization, heuristics or reinforcement learning'
EX=$(ls -t runs/*_exact_search.jsonl | head -1); SE=$(ls -t runs/*_semantic_search.jsonl | head -1)
$PY $PL/scripts/fetch_pdf.py --from $EX; $PY $PL/scripts/fetch_pdf.py --from $SE
$PY $PL/scripts/rank.py --abstracts $EX,$SE --dry      # token estimate, no API call
$PY $PL/scripts/rank.py --abstracts $EX,$SE
```

The two searches gave 167 distinct works and 73 open-access PDFs; the rest came back as `MANUAL` lines with the publisher page. The first Voyage run sent about 3.1M tokens; `--budget` (15M by default) stops a run before any API call. The output, [`runs/2026-10-18_0317_entanglement-scheduling_rank.csv`](examples/entanglement-scheduling/runs/2026-10-18_0317_entanglement-scheduling_rank.csv), has one row per paper with its rank, citation, link and `start_pages`, the page ranges where the queries agree.

## How ranking works

`rank.py` cuts each PDF's bibliography, splits the text into 1,200-token windows labelled with their pages, picks each paper's 3 best windows per query with `voyage-4-large` embeddings plus BM25, scores the paper with `rerank-3`, and combines the per-query ranks by Reciprocal Rank Fusion. `--provider local` uses `potion-science-32M` instead: free and offline, rougher, English only. Details: [`REFERENCE.md`](REFERENCE.md#how-ranking-works).

## Benchmarks

[`examples/litsearch-eval`](examples/litsearch-eval) can be rerun from this repository: 48 [LitSearch](https://huggingface.co/datasets/princeton-nlp/LitSearch) questions, each pointing at one known paper among about 20 on-topic PDFs. The `subject` queries were written blind and frozen with SHA-256 before any ranking. Voyage provider.

| Order | hit@3 | hit@5 | hit@10 | MRR |
| --- | --- | --- | --- | --- |
| Random (expected value) | 0.16 | 0.26 | 0.52 | 0.18 |
| paper-lector, default (`main` + `subject`) | 0.75 | 0.88 | 0.96 | 0.72 |
| paper-lector, `main` only | 0.75 | 0.85 | 0.96 | 0.71 |

hit@k is the share of questions with the known paper in the top k; MRR is the mean of 1 / its rank. Not shown yet: whether the full text beats an abstract-only reranker (an earlier, smaller test found the order no better; [`baselines20.py`](examples/litsearch-eval/baselines20.py) runs the comparison here), and fields outside machine learning and NLP. What the full text adds for certain is `start_pages`. Numbers and caveats: [`MINI-TEST.md`](examples/litsearch/MINI-TEST.md), [`results20.json`](examples/litsearch-eval/results20.json).

## Tests

```bash
.venv/bin/pip install pytest==9.1.1
.venv/bin/python -m pytest -q
```

The tests run offline and need `pdftotext`. See [`CHANGELOG.md`](CHANGELOG.md), [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md). License: [MIT](LICENSE).
