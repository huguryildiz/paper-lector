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
  <a href="#example-quantum-network-scheduling">Example</a>
  &nbsp;·&nbsp;
  <a href="#search-modes">Search modes</a>
  &nbsp;·&nbsp;
  <a href="#how-ranking-works">How it works</a>
  &nbsp;·&nbsp;
  <a href="REFERENCE.md">Reference</a>
</h3>

---

<p align="center">
  <img src="assets/example-output.svg" alt="Example output: the top 5 of 40 PDFs for a LitSearch question on factuality and hallucination detection in abstractive summarization, with the pages to start reading" width="880">
</p>

<p align="center"><sub>A real run on 40 open-access PDFs: one <a href="https://huggingface.co/datasets/princeton-nlp/LitSearch">LitSearch</a> question, its 5 gold papers and 35 distractors from nearby topics. MAIN and SUBJECT are each paper's rank on those two queries; START AT is the first window the reranker read for the main query. The papers, the run record and the script that draws this image are in <a href="examples/litsearch">examples/litsearch</a>.</sub></p>

## Overview

paper-lector is an agent skill for Claude Code and Codex with three scripts:

- `openalex_search.py` searches OpenAlex (keyword, semantic, citing works, references).
- `fetch_pdf.py` downloads open-access PDFs and lists the rest for manual download.
- `rank.py` ranks your own PDFs against a few frozen research-question queries and tells you which pages to read first.

[`SKILL.md`](SKILL.md) is the guide the agent reads. [`REFERENCE.md`](REFERENCE.md) has every option, output file and edge case.

## Install

You need Python 3.12 and `pdftotext` from poppler (`brew install poppler` on macOS).

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p ~/.claude/skills ~/.codex/skills
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector   # Claude Code
ln -s ~/Documents/GitHub/paper-lector ~/.codex/skills/paper-lector    # Codex
```

The symlink is what lets the agent find the skill; make the one for the agent you use, or both.

Add your API keys: `OPENALEX_API_KEY` for search and fetch, `VOYAGE_API_KEY` for ranking. Put them in `~/.config/paper-lector/.env` (shared by all projects) or in a project's `.env`.

```bash
mkdir -p ~/.config/paper-lector
cp .env.example ~/.config/paper-lector/.env
```

Then, once and while online, check `pdftotext` and download the pinned tokenizer:

```bash
.venv/bin/python scripts/rank.py --setup
```

Without a Voyage key, add `--provider local` to that command; it also downloads the local model, [`potion-multilingual-128M`](https://huggingface.co/minishlab/potion-multilingual-128M) (531 MB).

## Example: quantum network scheduling

[`examples/entanglement-scheduling`](examples/entanglement-scheduling) is a complete run made with these scripts. The question:

> Which methods (optimization, heuristics, reinforcement learning) have been used to schedule entanglement distribution in a multi-user quantum network, and with which metrics were they compared?

**1. Config.** `literature.json` sits at the project root, and its paths are relative to it.

```json
{
  "pdf_dirs": ["pdfs"],
  "download_dir": "pdfs",
  "queries": "queries/queries.json",
  "rank": {"provider": "voyage"}
}
```

**2. Queries.** [`queries/queries.json`](examples/entanglement-scheduling/queries/queries.json) holds the question and five labelled queries (`main`, `subject`, `approach`, `outcome`, `comparison`), each written as a full sentence with a keyword string; the first four are fused. Once a queries file has produced results, it stays as it is; a changed question gets a new file.

**3a. With an agent.** Open the project in Claude Code or Codex and ask:

> Find and rank papers on how entanglement distribution is scheduled among many users of a quantum network.

The agent asks which search modes to run and shows its queries for approval. It then downloads the open-access PDFs and fills the query slots through a few questions. After a dry run it ranks the papers and reports the top 10 with the pages to start on.

**3b. From the shell.**

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python

# search OpenAlex two ways, compare, download the open-access PDFs
$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --exact '("quantum network" OR "quantum networks" OR "quantum internet") AND (entangl*) AND (schedul*)'
$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --semantic 'Scheduling entanglement distribution among multiple users in a quantum network with optimization, heuristics or reinforcement learning'
$PY $PL/scripts/search_overlap.py runs/*_exact_search.jsonl runs/*_semantic_search.jsonl
$PY $PL/scripts/fetch_pdf.py --from runs/2026-10-18_0144_entanglement-scheduling_exact_search.jsonl
$PY $PL/scripts/fetch_pdf.py --from runs/2026-10-18_0143_entanglement-scheduling_semantic_search.jsonl

# count tokens without calling the API, then rank PDFs on full text and every paper on its abstract
A=runs/2026-10-18_0144_entanglement-scheduling_exact_search.jsonl,runs/2026-10-18_0143_entanglement-scheduling_semantic_search.jsonl
$PY $PL/scripts/rank.py --abstracts $A --dry
$PY $PL/scripts/rank.py --abstracts $A
```

The keyword search returned 137 works and the semantic search the 50 closest. They share 20, so 167 distinct works came out, and `search_overlap.py` reported LOW OVERLAP: only 40% of the semantic works were in the keyword results. `fetch_pdf.py` downloaded 73 open-access PDFs. For each paper it could not get, it wrote a `MANUAL` line with the publisher page, where the PDF can be downloaded by hand.

Ranking scored the 73 PDFs on full text and 149 papers on their abstracts; 76 of these had no PDF, and 8 had no abstract and stayed unranked. Rerank used 1.59M tokens and every embedding came from the cache: a rerun pays only for new text, and `rank.py` stops before any API call if the token estimate is above 15M.

**4. Read the output.** [`runs/2026-10-18_0151_entanglement-scheduling_rank.csv`](examples/entanglement-scheduling/runs/2026-10-18_0151_entanglement-scheduling_rank.csv) has one row per paper, PDFs first by `fused_rank`, then the papers with no PDF by `abs_fused_rank`. The first columns are for reading: the full-text rank and the abstract rank, the citation, a link, the citation count and its percentile, and `start_pages`. `start_pages` gives up to three page ranges where the fused queries' windows agree. Every other column follows. `_rank_run.json` records everything needed to repeat the run, and runs are never overwritten. Scanned PDFs with no text are skipped and listed in the dry run and `_rank_run.json`.

A high rank means the text resembles the question. It does not mean the paper is good or that it answers the question.

**5. Without a Voyage key.** The same 73 PDFs ranked with `--provider local` (model2vec, no API call, 30 seconds) gave [`runs/2026-10-18_0246_entanglement-scheduling_rank-local.csv`](examples/entanglement-scheduling/runs/2026-10-18_0246_entanglement-scheduling_rank-local.csv). Its order agrees with Voyage at Spearman 0.71 on full text and 0.72 on abstracts (139 papers), but the two top 10s share only 4 papers. Voyage's top 10 with the place each paper got from the local run:

| Voyage | Local | Paper |
| ---: | ---: | --- |
| 1 | 5 | Ni & Ho (2026), Scheduling concurrent entanglement requests in quantum networks |
| 2 | 2 | Li et al. (2021), Effective routing design for remote entanglement generation |
| 3 | 25 | Ni et al. (2025), Entanglement request scheduling using deep Q-network |
| 4 | 22 | Gu et al. (2023), ESDI: entanglement scheduling and distribution |
| 5 | 6 | Abreu et al. (2026), QoS-aware reinforcement learning routing |
| 6 | 4 | Kumar et al. (2026), Making quantum networks work: routing |
| 7 | 31 | Rode et al. (2026), Learning policies for simultaneous entanglement requests |
| 8 | 34 | Halder et al. (2024), Optimal routing and end-to-end entanglement distribution |
| 9 | 19 | Fittipaldi et al. (2022), Linear algebraic framework for the quantum internet |
| 10 | 44 | Tran et al. (2026), Dynamic entanglement packet scheduling |

The local run keeps the papers that share the question's words, but loses several that answer its specific part, scheduling among many users: three scheduling papers drop from the top 4 and top 10 to places 22 to 44, and Erçetin & Gedik (2026), *Fidelity-age-aware scheduling*, drops from 15 to 47. Its first place is a general survey, Gkelias et al. (2026), *Quantum networking fundamentals*, which Voyage puts 22nd. Static token vectors measure shared vocabulary; Voyage's reranker reads the query and the passage together. Use `local` to get started, and read further down its list than you would with Voyage.

## Search modes

`openalex_search.py` finds papers in OpenAlex in four ways. With an agent, ask for a search ("find papers on energy-aware routing in underwater networks") and it asks which modes to use, then shows the queries it wrote for you to approve.

| Mode | Flag | What you get | Use it when |
| --- | --- | --- | --- |
| Keyword | `--exact '<boolean query>'` | Every work whose title or abstract matches the words, with `AND`, `OR`, `NOT` and `*` wildcards (all pages need `OPENALEX_API_KEY`; without it, the first 200). Repeatable | You want a complete search and know the field's words |
| Semantic | `--semantic '<sentence>'` | The 50 works closest in meaning to a sentence. Can change between runs | You are new to a field, or its papers use many names for one idea |
| Citing works | `--cites <id>` | Works that cite one paper (all pages need `OPENALEX_API_KEY`; without it, the first 200) | You want what came after a key paper |
| References | `--refs <id>` | Every work one paper cites | You want what a key paper built on |

`<id>` is a DOI, an arXiv id or an OpenAlex W id. Each mode writes a JSONL file that `fetch_pdf.py --from` downloads from. Keyword and semantic searches catch different papers, so run both; `search_overlap.py` then shows how many semantic works the keyword search also found. On the entanglement-scheduling example it was 20 of 50, under half, and the agent then names the words the keyword query lacks and proposes a revised query.

## How ranking works

1. `pdftotext` extracts each PDF and the bibliography is cut off.
2. The text is split into 1,200-token windows, each labelled with its pages.
3. For each query, the 3 best windows per paper are picked by `voyage-4-large` embeddings plus BM25.
4. `rerank-3` scores each paper on its abstract plus those windows.
5. The per-query ranks are combined with Reciprocal Rank Fusion into `fused_rank`.

Without a Voyage key, set `"rank": {"provider": "local"}` (or `--provider local`): no API call; ranking uses the model2vec model `potion-multilingual-128M` (a one-time 531 MB download) and gives a rougher order than Voyage. PDFs in Turkish, German, French, Spanish, Italian, Portuguese and Russian are handled too. The formula, a worked example and the language rules are in [`REFERENCE.md`](REFERENCE.md#how-ranking-works).

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

The tests run offline and need `pdftotext` on `PATH`.

## License

[MIT](LICENSE)
