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
  <a href="#search-modes">Search modes</a>
  &nbsp;·&nbsp;
  <a href="#how-ranking-works">How it works</a>
  &nbsp;·&nbsp;
  <a href="#script-options">Options</a>
  &nbsp;·&nbsp;
  <a href="#ranking-providers">Providers</a>
  &nbsp;·&nbsp;
  <a href="#tests">Tests</a>
</h3>

---

<p align="center">
  <img src="assets/example-output.svg" alt="Example output: the top 5 of 40 PDFs for a LitSearch question on factuality and hallucination detection in abstractive summarization, with the pages to start reading" width="880">
</p>

<p align="center"><sub>A real run on 40 open-access PDFs: one <a href="https://huggingface.co/datasets/princeton-nlp/LitSearch">LitSearch</a> question, its 5 gold papers and 35 distractors from nearby topics. MAIN and SUBJECT are each paper's rank on those two queries; START AT is the first window the reranker read for the main query. The papers, the run record and the script that draws this image are in <a href="examples/litsearch">examples/litsearch</a>.</sub></p>

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
mkdir -p ~/.claude/skills ~/.codex/skills
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector   # Claude Code
ln -s ~/Documents/GitHub/paper-lector ~/.codex/skills/paper-lector    # Codex
```

The symlink is what lets the agent find the skill; make the one for the agent you use, or both.

API keys: copy `.env.example` to `~/.config/paper-lector/.env` (shared by all projects) or to a project's `.env`, and fill in `OPENALEX_API_KEY` (search, fetch) and `VOYAGE_API_KEY` (rank with the default `voyage` provider). Lookup order: the environment, then the project's `.env`, then `~/.config/paper-lector/.env`.

```bash
mkdir -p ~/.config/paper-lector
cp .env.example ~/.config/paper-lector/.env
```

Then, once and while online:

```bash
.venv/bin/python scripts/rank.py --setup
```

It checks that `pdftotext` is on `PATH` (and prints the install command if not) and downloads the `voyage-4-large` tokenizer from Hugging Face into `~/.cache/paper-lector/`. The tokenizer is pinned to one Hugging Face revision and checked against its SHA-256, so two machines cut the same windows; `requirements.txt` pins the Python packages for the same reason. Every rank run needs that tokenizer to cut windows and count tokens, including `--dry` and the `bm25` provider. After `--setup`, the `bm25` provider works fully offline. If the tokenizer is missing on an offline machine, `rank.py` stops and says where to put the file; an interrupted download leaves no half-written file behind.

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

The agent first counts the PDFs in `pdf_dirs`. If a folder is missing or empty, it does not start the questions; it offers to search OpenAlex and download open-access papers, to point to another folder, or to stop. Then it asks seven questions in a fixed order: the six query slots, then which slots to fuse. Each screen holds as many questions as the agent's question tool allows, so Claude Code shows two screens and Codex may show three. For each slot you take the agent's suggestion, type your own wording, or leave it empty (`main` is required). The agent writes the queries from your answers and shows them as a table for you to edit. After you approve them, it freezes the file, runs a dry run to report the token estimate, runs the ranking, and reports the top 10 with the pages to start on.

**3b. From the shell.** The same steps by hand, run from anywhere inside the project:

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python

# find papers and download the open-access ones
$PY $PL/scripts/openalex_search.py --exact '(underwater AND acoustic) AND (rout* OR relay*) AND (lifetime OR energy)' --out runs/uw.jsonl
$PY $PL/scripts/fetch_pdf.py --from runs/uw.jsonl

# count tokens without calling the API, then rank
$PY $PL/scripts/rank.py --out runs/uw --dry
$PY $PL/scripts/rank.py --out runs/uw

# later, after adding PDFs: same queries, new --out; cached embeddings are reused
$PY $PL/scripts/rank.py --out runs/uw-2026-10-20
```

`fetch_pdf.py` saves into `download_dir` and prints a `MANUAL` line for each paper it could not get (often a publisher returning 403); download those yourself. An `ERROR` line means the OpenAlex lookup itself failed (a bad key, a dropped connection), and a `SKIP` line a JSONL record with no DOI, arXiv or OpenAlex id. It ends with a count of each and exits with status 1 if any paper was not obtained. Every saved PDF gets a line in `fetch_log.jsonl` in the download folder with status `OK`, the id, the URL it came from (so you can tell a preprint from the published version), the file name and its SHA-256. Every `MANUAL` paper gets a line there too, with its title and landing URL, so the list of papers to download by hand outlives the terminal. It skips DOIs already in the `sources` table, and file names end in a short hash of the DOI so two papers with the same author, year and title words don't overwrite each other. `rank.py` refuses to call the API if the estimate is above `--budget` (15M tokens by default). The estimate is an upper bound computed before any call: every window, the queries, and each rerank package with its abstract, page labels and query. `--budget` checks that estimate; it does not meter the run as it goes. Voyage embeddings are cached in `~/.cache/paper-lector/embeddings.sqlite` after each batch, so a rerun, or a run restarted after a crash, pays only for new text; the estimate still counts everything. Dropped connections, timeouts, cut-off responses and HTTP 429/5xx are retried, for API calls and PDF downloads alike.

**4. Read the output.** `runs/uw_hybrid.csv` has one row per paper, sorted by `fused_rank`, which combines only the queries listed in `fuse`; each query also has its own `_rank` and `_score` columns. The `<query>_pages` columns give the pages that were scored, which is a sensible place to start reading. Paper ids are the `sources` key or the file name; two files with the same name become `Name` and `Name-2`. An id that starts with `=`, `+`, `-` or `@` gets a `'` in front in the CSV, so a spreadsheet does not run it as a formula. `runs/uw_run.json` records the question, queries, fuse list, models, parameters, each paper's id, path and SHA-256, token usage, the paper-lector commit and the versions of Python, numpy, tokenizers, pdftotext and the tokenizer, so the run can be repeated. `rank.py` never overwrites a run: it stops if any output of that `--out` already exists (also a CSV left by a run that crashed before writing `_run.json`), and so does a run whose question, queries or fuse list differ from the saved run. While a run is going, `<out>_run.lock` keeps a second run from using the same `--out`; if a run is killed, the lock stays, and the error says to delete it. A high rank means the text resembles the question. It does not mean the paper is good or that it answers the question.

**5. Check what was left out or counted twice.** Both the dry run and `_run.json` report two kinds of problem paper:

- PDFs with no extractable text (scanned images or protected files), and PDFs on which `pdftotext` fails or runs longer than 5 minutes, are skipped and listed under `corpus.skipped` with the reason. Partial text from a failed extraction is never ranked. They are missing from the order; run OCR on them or read them yourself. A `--ids` run stops if any listed paper has no text, since its frozen corpus would be incomplete.
- Byte-identical copies of a PDF are skipped with a note. Papers whose abstracts share most of their words (often a preprint and its published version) are ranked both times and listed under `corpus.possible_duplicates`. Move one copy out of `pdf_dirs` and rerun into a new `--out`.

See [`SKILL.md`](SKILL.md) for the query-writing rules and the full agent workflow.

## Search modes

`openalex_search.py` finds papers in OpenAlex in four ways. With an agent, ask for a search ("find papers on energy-aware routing in underwater networks") and it asks which modes (you can pick more than one), then shows the queries it wrote for you to run, edit or change. If your request already names the mode ("papers citing ..."), it skips that question.

| Mode | Flag | What you get | Use it when |
| --- | --- | --- | --- |
| Keyword | `--exact '<boolean query>'` | Every work whose title or abstract matches the words, with `AND`, `OR`, `NOT` and `*` wildcards (`rout*` matches routing and routes). The same query on the same OpenAlex data gives the same list | You want a complete, repeatable search and know the field's words |
| Semantic | `--semantic '<sentence>'` | The 50 works closest in meaning to a sentence, even when they use other words. The list can change between runs | You are new to a field, or its papers use many names for one idea |
| Citing works | `--cites <id>` | Works that cite one paper | You have a key paper and want what came after it |
| References | `--refs <id>` | Every work one paper cites | You want what a key paper built on |

`<id>` is a DOI, an arXiv id or an OpenAlex W id. Each mode writes a JSONL file that `fetch_pdf.py --from` downloads from, and records which works are already in your `sources` table. A keyword search and a semantic one on the same topic catch different papers; you can run both and fetch from both files.

These modes only find papers. Ranking your own PDFs is a separate step (`rank.py`) and always reads by meaning with the Voyage provider, whichever mode found the papers.

## How ranking works

1. `pdftotext` extracts the whole PDF. The bibliography is cut only when its heading is found with confidence; appendices stay.
2. The text is split into 1,200-token windows with 200 tokens of overlap, each labelled with the PDF pages it covers.
3. For each paper and query, windows are ordered by Reciprocal Rank Fusion (k = 60) of `voyage-4-large` cosine similarity and BM25 on the query's keyword string. The best 3 are kept.
4. `rerank-3` scores each paper once per query on its abstract (or its first 1,000 tokens when no abstract is found) plus those 3 windows.
5. `fused_rank` is RRF over the queries in `fuse`.

BM25 statistics depend on the whole collection, so after adding PDFs rerank everything rather than only the new files.

With `--abstracts`, `rerank-3` also scores every paper on its abstract alone, so papers whose PDF you could not get still get a place in an order. That order is kept apart from the full-text one. On 16 papers of one search, abstract-only scores were 0.06 lower than full-text scores on average, so a paper ranked on its abstract among full-text papers fell 3 to 5 places (up to 12) for lack of a PDF. Ranked against each other on abstracts alone, the same papers kept much of the full-text order (rank correlation 0.76 to 0.88 per query).

### PDFs in other languages

`rank.py` finds abstract, introduction, bibliography and appendix headings in English, Turkish, German, French, Spanish, Italian, Portuguese and Russian (for example *Özet*, *Zusammenfassung*, *Résumé*, *Kaynaklar*, *Références*, *Литература*). Numbered reference lines with a year also count as a bibliography. In other languages it falls back to the first 1,000 tokens and keeps the bibliography; the dry run shows this as `-` in the `abs` and `bib` columns.

`voyage-4-large` and `rerank-3` are multilingual, so the English `text` of each query works on those papers as it is. BM25 matches words, so add the other language's terms to `keywords` next to the English ones (`energy routing enerji yönlendirme`). BM25 tokenises on Unicode letters and drops Turkish stop words. Chinese, Japanese and Korean text has no spaces between words and BM25 does not work on it; use the `voyage` provider for those papers.

## Script options

All three scripts look for `literature.json` from the current folder up to the project root (the first folder with `.git`); `--config` points to another one.

| Script | Option | What it does |
| --- | --- | --- |
| `openalex_search.py` | `--semantic TEXT` | Meaning-based search; at most 50 results and not reproducible |
| | `--exact QUERY` | Boolean query on title and abstract, unstemmed (`rout*` for routing and routes); all pages. The same query on the same OpenAlex snapshot gives the same list |
| | `--cites ID` / `--refs ID` | Works citing ID, or all works ID references (DOI, arXiv id or OpenAlex W id) |
| | `--out FILE` | JSONL output, one work per line, with abstract, PDF link and `in_sources` |
| | `--max N` | Stop after N records (0 = all) |
| `fetch_pdf.py` | `ID ...` | Fetch the listed works (DOI, arXiv id or OpenAlex W id, also as doi.org or arxiv.org URLs) |
| | `--from FILE` | Fetch every work in a JSONL from `openalex_search.py`; records without any id get a `SKIP` line |
| | `--dest DIR` | Save here instead of `download_dir` |
| `rank.py` | `--setup` | Check `pdftotext`, download the tokenizer, exit |
| | `--out PREFIX` | Output prefix for `_hybrid.csv` (or `_bm25.csv`) and `_run.json` |
| | `--dry` | Build windows, print counts and the token estimate; no API call |
| | `--budget N` | Stop before any API call if the estimate is above N tokens (default 15M) |
| | `--provider voyage\|bm25` | Override `rank.provider` for this run |
| | `--queries FILE` / `--dirs A,B` | Override `queries` or `pdf_dirs` from the config |
| | `--ids CSV` | Rank exactly the ids in the CSV's `paper` column (frozen corpus). With a `sha256` column (copy it from `corpus.files` in `_run.json`) a changed file under the same id stops the run. An empty list stops it too |
| | `--abstracts FILE[,FILE]` | Search JSONL files: rank every paper on its abstract alone as well (`abs_fused_rank`), including search results with no PDF (`source` = `abstract_only`, listed after the PDFs). A record is tied to its PDF through the sources DOI, an `OK` line in `fetch_log.jsonl` or its title on the PDF's first page. The two orders are kept apart: abstract-only scores run lower than full-text ones |
| | `--expect A,B` | Paper ids you expect in the first query's top 10, written down before the run |
| | `--variants hybrid,dense` | Add a dense-only ablation (voyage only) |

`fetch_pdf.py` keeps a file only if it starts with `%PDF`, never overwrites an existing file, and does not save a download that is byte-identical to a PDF already in the folders. It writes to a temporary file first, so a crash never leaves a half PDF under the final name. It fetches only http(s) URLs whose host resolves to a public address, and checks every redirect the same way, so a URL in OpenAlex data cannot point it at local files, this machine or the local network. The check resolves the name before connecting; a DNS server that answers differently a moment later is not covered. Each download stops at 100 MB, or after 5 minutes counting all retries; a response shorter than its declared length is retried and never saved. It never works around paywalls, logins or bot checks.

The paths in `literature.json` and in the `sources` CSV are trusted: they can point anywhere on disk, and the scripts read what they name. Do not run the scripts on a project config you have not read.

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

The tests run offline: small generated PDFs, sample text with headings in each supported language, a word tokenizer and a fake Voyage API. They need `pdftotext` on `PATH`. One test uses the real tokenizer and is skipped until `rank.py --setup` has run. GitHub Actions runs the suite on every push (`.github/workflows/tests.yml`).

## License

[MIT](LICENSE)
