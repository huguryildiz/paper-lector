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

A high rank means the text resembles the question, not that the paper is good or answers it. [`SKILL.md`](SKILL.md) is the guide the agent reads; [`REFERENCE.md`](REFERENCE.md) has every option, output file and edge case.

Tools that answer questions over PDFs, such as PaperQA2 or NotebookLM, write an answer with citations. paper-lector writes no answer: it gives an order and page ranges, which you check by reading. Hosted research assistants such as Elicit, Undermind or Consensus search and summarize on their side; paper-lector ranks the PDFs you already hold, keeps every input and output as a local file, and records what a rerun needs (frozen queries, the SHA-256 of every PDF, versions). It suits a collection larger than you can read for one question.

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

- `OPENALEX_API_KEY`, free and optional, for complete searches: [openalex.org/signup](https://openalex.org/signup).
- `VOYAGE_API_KEY` for ranking with the default provider: [dashboard.voyageai.com](https://dashboard.voyageai.com/organization/api-keys). An account with no payment method gets low rate limits and may stop on HTTP 429; the free tokens apply either way. Without a key, rank with `--provider local`.

```bash
mkdir -p ~/.config/paper-lector
install -m 600 .env.example ~/.config/paper-lector/.env    # then fill in the keys
.venv/bin/python scripts/rank.py --setup                   # once, online; add --provider local without a Voyage key
```

## Example

[`examples/entanglement-scheduling`](examples/entanglement-scheduling) is a complete run on this question:

> Which methods (optimization, heuristics, reinforcement learning) have been used to schedule entanglement distribution in a multi-user quantum network, and with which metrics were they compared?

With an agent, open a project folder in Claude Code or Codex and ask for it in your own words, for example "find and rank papers on how entanglement distribution is scheduled among many users of a quantum network". The agent proposes search queries, downloads the open-access PDFs, asks a few questions to fill the query slots, runs a dry run for the token estimate, and reports the top 10 with the pages to start on.

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

The two searches gave 167 distinct works and 73 open-access PDFs; the rest came back as `MANUAL` lines with the publisher page. `fetch_pdf.py` exits with status 1 when any paper is missing. A first Voyage run on the 73 PDFs and 139 abstracts sends about 3.1M tokens; embeddings are cached for reruns, reranking is paid each time, and `--budget` (15M by default) stops a run before any API call.

The output, [`runs/2026-10-18_0317_entanglement-scheduling_rank.csv`](examples/entanglement-scheduling/runs/2026-10-18_0317_entanglement-scheduling_rank.csv), has one row per paper: rank, citation, link, citation count and `start_pages`, the page ranges where the queries agree. `_rank_run.json` records what is needed to repeat the run, including the SHA-256 of every PDF and of the queries file.

## Search modes

| Mode | Flag | What you get |
| --- | --- | --- |
| Keyword | `--exact '<boolean query>'` | Every work whose title or abstract matches (`AND`, `OR`, `NOT`, `*`; without a key, the first 200) |
| Semantic | `--semantic '<sentence>'` | The 50 works closest in meaning; can change between runs |
| Citing works | `--cites <id>` | Works citing one paper |
| References | `--refs <id>` | Works one paper cites |

`<id>` is a DOI, arXiv id or OpenAlex W id. Keyword and semantic searches find different papers, so run both; `search_overlap.py` reports how much they share.

## How ranking works

1. `pdftotext` extracts each PDF and the bibliography is cut off.
2. The text is split into 1,200-token windows labelled with their pages.
3. For each query, the 3 best windows per paper are picked by `voyage-4-large` embeddings plus BM25.
4. `rerank-3` scores each paper on its abstract plus those windows.
5. Reciprocal Rank Fusion combines the per-query ranks into `fused_rank`.

`--provider local` replaces Voyage with an English model2vec model, `potion-science-32M` (130 MB, no API call). It is faster and free but rougher. For PDFs that are not in English, use Voyage. Details are in [`REFERENCE.md`](REFERENCE.md#how-ranking-works).

## Benchmarks

One set can be rerun from this repository, [`examples/litsearch-eval`](examples/litsearch-eval): 48 [LitSearch](https://huggingface.co/datasets/princeton-nlp/LitSearch) questions, each pointing at one known paper, with 20 PDFs per question (8 and 13 in two questions): the known paper and the first candidates another search pipeline (DEIXIS) retrieved for the same question, so the distractors are on topic. The `subject` queries were written blind from the question and frozen with SHA-256 before any ranking. Voyage provider.

| Order | hit@3 | hit@5 | hit@10 | MRR |
| --- | --- | --- | --- | --- |
| Random (expected value) | 0.16 | 0.26 | 0.52 | 0.18 |
| paper-lector, default (`main` + `subject`) | 0.75 | 0.88 | 0.96 | 0.72 |
| paper-lector, `main` only | 0.75 | 0.85 | 0.96 | 0.71 |

hit@k is the share of questions with the known paper in the top k; MRR is the mean of 1 / its rank.

What this does not show yet:

- **Whether the full text helps.** BM25 on the full text and the same reranker on the abstract alone have not been run on this set; [`baselines20.py`](examples/litsearch-eval/baselines20.py) runs both. In an earlier test on 19 of these questions with a median of 32 PDFs each (its working folder was not kept), an abstract-only reranker (`rerank-3-lite`) put the known paper in the top 3 in 11 of the 13 questions where its candidate list held it; paper-lector did so in 12 with `main` only and in 8 with the default. So far the order is no better than an abstract reranker's; what the full text adds for certain is `start_pages`.
- **Other fields.** LitSearch questions are about machine learning and NLP papers.

Two smaller checks, both with the local model: it told seven IEEE surveys' references apart from a neighbouring survey's with an average precision of 0.60, against 0.35 for a random order, but the three quantum surveys share about half their references, and for one of them it did no better than random. On the example's 73 PDFs its order agrees with Voyage's at Spearman 0.79, and the two top 10s share 5 papers.

Numbers and caveats: [`examples/litsearch/MINI-TEST.md`](examples/litsearch/MINI-TEST.md) and [`results20.json`](examples/litsearch-eval/results20.json).

## Tests

```bash
.venv/bin/pip install pytest==9.1.1
.venv/bin/python -m pytest -q
```

The tests run offline and need `pdftotext`. Tests that use the real tokenizer and local models are skipped until `rank.py --setup --provider local` has run.

## Versions and issues

See [`CHANGELOG.md`](CHANGELOG.md), [`CONTRIBUTING.md`](CONTRIBUTING.md) and, for security issues, [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE)
