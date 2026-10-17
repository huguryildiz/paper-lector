<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img src="assets/icon.svg" alt="paper-lector logo" width="120" height="120">
</p>

<h1 align="center">paper-lector</h1>

<p align="center">
  <strong>Agent Skill for Claude Code and Codex</strong><br>
  <sub>Ranks research PDFs and suggests starting pages; reading leads, not evidence.</sub>
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
  <a href="#example-underwater-routing-papers">Example</a>
  &nbsp;·&nbsp;
  <a href="#ranking-providers">Providers</a>
  &nbsp;·&nbsp;
  <a href="#tests">Tests</a>
</h3>

---

## Overview

paper-lector is an agent skill for Claude Code and Codex with three scripts:

- `openalex_search.py` searches OpenAlex (semantic, exact boolean, citing works, references).
- `fetch_pdf.py` downloads open-access PDFs (arXiv first, then OpenAlex locations) and lists the rest for manual download.
- `rank.py` ranks your own PDF collection against a few frozen research-question queries. It splits each PDF into page-labelled windows, picks the best windows per paper with BM25 plus `voyage-4-large` embeddings, scores each paper with `rerank-3`, and fuses the ranks of the queries listed in `fuse` (`main` and `subject` by default) into a reading order. Without a Voyage key it can run on BM25 alone (see "Ranking without an API key").

`SKILL.md` is the full guide that the agent reads.

## Install

You need Python 3.12 and `pdftotext` from poppler (`brew install poppler` on macOS).

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector   # Claude Code
ln -s ~/Documents/GitHub/paper-lector ~/.codex/skills/paper-lector    # Codex
```

The symlink is what lets the agent find the skill; make the one for the agent you use, or both.

API keys: copy `.env.example` to `~/.config/paper-lector/.env` (shared by all projects) or to a project's `.env`, and fill in `OPENALEX_API_KEY` (search, fetch) and `VOYAGE_API_KEY` (rank with the default `voyage` provider). Lookup order: the environment, then the project's `.env`, then `~/.config/paper-lector/.env`.

```bash
mkdir -p ~/.config/paper-lector
cp .env.example ~/.config/paper-lector/.env
```

On its first run, `rank.py` downloads the `voyage-4-large` tokenizer from Hugging Face into `~/.cache/paper-lector/`. It uses it to cut windows and count tokens, so the download also happens with `--dry` and with the `bm25` provider.

## Example: underwater routing papers

Suppose a project folder holds a few dozen PDFs on underwater acoustic sensor networks, and the question is which next hop a node should pick so the network lives longer.

**1. Config.** Put `literature.json` at the project root. Paths are relative to that file.

```json
{
  "pdf_dirs": ["literature/pdfs"],
  "download_dir": "literature/pdfs/new",
  "queries": "literature/queries.json",
  "rank": {"provider": "voyage"}
}
```

`rank` is optional; `voyage` is the default. An optional `sources` CSV (the papers you already hold, with `key`, `pdf_path` and `doi` columns) can be added too; [`examples/literature.json`](examples/literature.json) shows it. If the CSV is missing, the scripts say so and carry on without it.

**2. Queries.** `literature/queries.json` holds the question and a few labelled queries (`main`, `subject`, `approach`, `outcome`, `context`, `comparison`). Each one has a full sentence for the embedding model and the reranker, plus a keyword string for BM25. [`examples/queries.json`](examples/queries.json) is the complete file for this example. Once you have seen results from a queries file, don't edit it; write a new file for a revised run.

**3a. With an agent.** Open the project in Claude Code or Codex and ask:

> Rank my PDFs for this question: which next hop should a node in an underwater acoustic sensor network choose so that the network lives longer?

The agent first checks that the PDF folders hold PDFs; if they are empty, it offers to search OpenAlex and download open-access papers. Then it asks seven questions in a fixed order: the six query slots, then which slots to fuse. Each screen holds as many questions as the agent's question tool allows, so Claude Code shows two screens and Codex may show three. For each slot you take the agent's suggestion, type your own wording, or leave it empty (`main` is required). The agent writes the queries from your answers and shows them as a table for you to edit. After you approve them, it freezes the file, runs a dry run to report the token estimate, runs the ranking, and reports the top 10 with the pages to start on.

**3b. From the shell.** The same steps by hand, run from anywhere inside the project:

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python

# find papers and download the open-access ones
$PY $PL/scripts/openalex_search.py --exact '(underwater acoustic) AND (routing OR relay) AND (lifetime OR energy)' --out runs/uw.jsonl
$PY $PL/scripts/fetch_pdf.py --from runs/uw.jsonl

# count tokens without calling the API, then rank
$PY $PL/scripts/rank.py --out runs/uw --dry
$PY $PL/scripts/rank.py --out runs/uw

# later, after adding PDFs: same queries, new --out; cached embeddings are reused
$PY $PL/scripts/rank.py --out runs/uw-2026-10-20
```

`fetch_pdf.py` saves into `download_dir` and prints a `MANUAL` line for each paper it could not get (often a publisher returning 403); download those yourself. It skips DOIs already in the `sources` table, and file names end in a short hash of the DOI so two papers with the same author, year and title words don't overwrite each other. `rank.py` refuses to call the API if the estimate is above `--budget` (15M tokens by default). Voyage embeddings are cached in `~/.cache/paper-lector/embeddings.sqlite` after each batch, so a rerun, or a run restarted after a crash, pays only for new text; the estimate still counts everything. Dropped connections, timeouts and HTTP 429/5xx are retried.

**4. Read the output.** `runs/uw_hybrid.csv` has one row per paper, sorted by `fused_rank`, which combines only the queries listed in `fuse`; each query also has its own `_rank` and `_score` columns. The `<query>_pages` columns give the pages that were scored, which is a sensible place to start reading. Paper ids are the `sources` key or the file name; two files with the same name become `Name` and `Name-2`. `runs/uw_run.json` records the question, queries, fuse list, models, token usage, commit and any PDFs skipped for having no text (scanned or protected, under `corpus.skipped`), so the run can be repeated. `rank.py` never overwrites a run: a second run into the same `--out` stops, and so does one whose question, queries or fuse list differ from the saved run. A high rank means the text resembles the question. It does not mean the paper is good or that it answers the question.

See [`SKILL.md`](SKILL.md) for the query-writing rules, the optional `sources` CSV, and the other options (`--cites`, `--refs`, `--expect`, `--ids`, `--variants`).

## Ranking providers

For now, `rank.py` supports one API: Voyage (`voyage-4-large` embeddings and `rerank-3`). Other embedding or rerank services, such as OpenAI, Cohere or a local Ollama model, are not supported yet. Adding one means a new name in `PROVIDERS` in `scripts/common.py`, a matching request and response format in `call()` in `scripts/rank.py`, and its own API key name. If you need one, open an issue.

### Ranking without an API key

Set `"rank": {"provider": "bm25"}` in `literature.json`, or pass `--provider bm25` for a single run. No key and no API call (apart from the one-time tokenizer download): windows are chosen by BM25 on each query's keyword string, and each paper is scored by BM25 on its abstract plus those windows. The output is `<out>_bm25.csv` with the same columns, and `_run.json` records the provider.

BM25 only matches words, so a paper that says "relay" when the query says "next hop" scores low. Expect a rougher order than with Voyage, and don't compare scores between the two providers.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

The tests run offline: small generated PDFs, a word tokenizer and a fake Voyage API.

## License

[MIT](LICENSE)
