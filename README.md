# paper-lector

Ranks research PDFs and suggests starting pages; reading leads, not evidence.

paper-lector is a Claude Code skill with three scripts:

- `openalex_search.py` searches OpenAlex (semantic, exact boolean, citing works, references).
- `fetch_pdf.py` downloads open-access PDFs (arXiv first, then OpenAlex locations) and lists the rest for manual download.
- `rank.py` ranks your own PDF collection against a few frozen research-question queries. It splits each PDF into page-labelled windows, picks the best windows per paper with BM25 plus `voyage-4-large` embeddings, scores each paper with `rerank-3`, and fuses the per-query ranks into a reading order. Without a Voyage key it can run on BM25 alone (see "Ranking without an API key").

`SKILL.md` is the full guide that Claude reads.

## Install

You need Python 3.12 and `pdftotext` from poppler (`brew install poppler` on macOS).

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector
```

The symlink is what lets Claude Code find the skill.

API keys: copy `.env.example` to `~/.config/paper-lector/.env` (shared by all projects) or to a project's `.env`, and fill in `OPENALEX_API_KEY` (search, fetch) and `VOYAGE_API_KEY` (rank with the default `voyage` provider). A key set in the environment takes precedence over both files.

```bash
mkdir -p ~/.config/paper-lector
cp .env.example ~/.config/paper-lector/.env
```

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

`rank` is optional; `voyage` is the default.

**2. Queries.** `literature/queries.json` holds the question and a few labelled queries (`main`, `subject`, `approach`, `outcome`, `context`, `comparison`). Each one has a full sentence for the embedding model and the reranker, plus a keyword string for BM25. [`examples/queries.json`](examples/queries.json) is the complete file for this example. Once you have seen results from a queries file, don't edit it; write a new file for a revised run.

**3a. With Claude.** Open the project in Claude Code and ask:

> Rank my PDFs for this question: which next hop should a node in an underwater acoustic sensor network choose so that the network lives longer?

Claude drafts the queries and shows them as a table for you to edit. After you approve them, it freezes the file, runs a dry run to report the token estimate, runs the ranking, and reports the top 10 with the pages to start on.

**3b. From the shell.** The same steps by hand, run from anywhere inside the project:

```bash
PL=~/.claude/skills/paper-lector
PY=$PL/.venv/bin/python

# find papers and download the open-access ones
$PY $PL/scripts/openalex_search.py --exact '(underwater acoustic) AND (routing OR relay) AND (lifetime OR energy)' --out runs/uw.jsonl
$PY $PL/scripts/fetch_pdf.py --from runs/uw.jsonl

# count tokens without calling the API, then rank
$PY $PL/scripts/rank.py --out runs/uw --dry
$PY $PL/scripts/rank.py --out runs/uw
```

`fetch_pdf.py` saves into `download_dir` and prints a `MANUAL` line for each paper it could not get (often a publisher returning 403); download those yourself. `rank.py` refuses to call the API if the estimate is above `--budget` (15M tokens by default).

**4. Read the output.** `runs/uw_hybrid.csv` has one row per paper, sorted by `fused_rank`. The `<query>_pages` columns give the pages the reranker read, which is a sensible place to start reading. `runs/uw_run.json` records the queries, models, token usage and commit, so the run can be repeated. A high rank means the text resembles the question. It does not mean the paper is good or that it answers the question.

See [`SKILL.md`](SKILL.md) for the query-writing rules, the optional `sources` CSV, and the other options (`--cites`, `--refs`, `--expect`, `--ids`, `--variants`).

## Ranking without an API key

Set `"rank": {"provider": "bm25"}` in `literature.json`, or pass `--provider bm25` for a single run. No key and no API call: windows are chosen by BM25 on each query's keyword string, and each paper is scored by BM25 on its abstract plus those windows. The output is `<out>_bm25.csv` with the same columns, and `_run.json` records the provider.

BM25 only matches words, so a paper that says "relay" when the query says "next hop" scores low. Expect a rougher order than with Voyage, and don't compare scores between the two providers.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

The tests run offline: small generated PDFs, a word tokenizer and a fake Voyage API.
