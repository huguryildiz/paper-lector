# paper-lector reference

The details behind the [README](README.md): what each script writes, how runs are kept apart, how ranking picks text, and every option. [`SKILL.md`](SKILL.md) is the agent's guide.

- [Setup](#setup)
- [Project layout](#project-layout)
- [Config and queries](#config-and-queries)
- [Fetching PDFs](#fetching-pdfs)
- [Ranking output](#ranking-output)
- [Problem papers](#problem-papers)
- [How ranking works](#how-ranking-works)
- [PDFs in other languages](#pdfs-in-other-languages)
- [Script options](#script-options)
- [Ranking providers](#ranking-providers)
- [Safety](#safety)
- [Tests](#tests)

## Setup

API keys are looked up in the environment, then the project's `.env`, then `~/.config/paper-lector/.env`. `OPENALEX_API_KEY` is used by search and fetch; without it, keyword and citing searches return only the first 200 works (references and semantic are not cut) and the daily budget is about 100 searches, shared by everyone on the same IP address. `VOYAGE_API_KEY` is used by `rank.py` with the default `voyage` provider.

`rank.py --setup` checks that `pdftotext` is on `PATH` (and prints the install command if not) and downloads the `voyage-4-large` tokenizer from Hugging Face into `~/.cache/paper-lector/`. The tokenizer is pinned to one Hugging Face revision and checked against its SHA-256, so two machines cut the same windows; `requirements.txt` pins the Python packages for the same reason. Every rank run needs that tokenizer to cut windows and count tokens, including `--dry` and the `local` provider. `rank.py --setup --provider local` also downloads the local model (`minishlab/potion-multilingual-128M`, 531 MB) into `~/.cache/paper-lector/potion-multilingual-128M/<revision>/`, pinned the same way and checked against its SHA-256 on every load; after that, the `local` provider works fully offline. A local run without the model downloads it first. The tokenizer's file name and the model's folder carry the first 7 characters of their pinned revision, so when a paper-lector update pins a newer one, the next run downloads it beside the old copy instead of stopping on a SHA-256 mismatch; the old file or folder can then be deleted. Runs made with different revisions give different scores; `_rank_run.json` records both revisions. If the tokenizer is missing on an offline machine, `rank.py` stops and says where to put the file; an interrupted download leaves no half-written file behind.

## Project layout

```
<project>/
├── literature.json            config; the scripts find it from any subfolder
├── sources.csv                papers you already hold (optional)
├── queries/
│   ├── <name>.json            frozen queries files, one per question or revision
│   └── questions.jsonl        every rank run of the project
├── pdfs/
│   ├── *.pdf
│   └── fetch_log.jsonl        what fetch_pdf.py saved, and what it could not get
└── runs/
    ├── <date>_<time>_<name>_<mode>_search.jsonl   with its .query.json
    ├── <date>_<time>_<name>_rank.csv              _rank-local.csv, _rank-dense.csv
    └── <date>_<time>_<name>_rank_run.json

~/.cache/paper-lector/         shared by every project on the machine
├── embeddings.sqlite          vectors (table emb) and where each came from (table src)
├── voyage-4-large-tokenizer-<revision>.json
└── potion-multilingual-128M/<revision>/   the local provider's model, 531 MB
```

Only `literature.json` has a fixed name. The other paths come from it (`pdf_dirs`, `download_dir`, `sources`, `queries`), so another layout works too; this one is what the agent writes for a new project. Search and rank outputs go to `runs/` next to the config unless `--out` says otherwise, and sort by time, so a search and the rank that used it sit together. `runs/` is reproducible from the logs and usually stays out of git, like the PDFs; [`examples/qnet`](examples/qnet) keeps its runs as a worked example.

## Config and queries

All three scripts look for `literature.json` from the current folder up to the project root (the first folder with `.git`); `--config` points to another one. Paths in it are relative to that file.

`rank` is optional; `voyage` is the default provider. An optional `sources` CSV (the papers you already hold, with `key`, `pdf_path` and `doi` columns) can be added too; [`examples/literature.json`](examples/literature.json) shows it. If the CSV is missing, the scripts say so and carry on without it.

The queries file holds the question, an optional short `name` for its output files (lowercase words joined by hyphens, at most 25 characters, kept for every later run of the same question) and a few labelled queries (`main`, `subject`, `approach`, `outcome`, `context`, `comparison`). Each one has a full sentence for the embedding model and the reranker, plus a keyword string for BM25. [`examples/queries/underwater-routing.json`](examples/queries/underwater-routing.json) is a complete file. Keep queries files in a `queries/` folder named after their `name`; the project's `questions.jsonl` (below) sits beside the config's queries file. Once you have seen results from a queries file, don't edit it; write a new file for a revised run.

With an agent, the agent first counts the PDFs in `pdf_dirs`. If a folder is missing or empty, it does not start the questions; it offers to search OpenAlex and download open-access papers, to point to another folder, or to stop. Then it asks seven questions in a fixed order: the six query slots, then which slots to fuse. Each screen holds as many questions as the agent's question tool allows, so Claude Code shows two screens and Codex may show three. For each slot you take the agent's suggestion, type your own wording, or leave it empty (`main` is required). The agent writes the queries from your answers and shows them as a table for you to edit. After you approve them, it freezes the file, runs a dry run to report the token estimate, runs the ranking, and reports the top 10 with the pages to start on.

## Fetching PDFs

`fetch_pdf.py` saves into `download_dir` and prints one line per paper:

- `MANUAL`: it could not get the paper (often a publisher returning 403); download it yourself.
- `ERROR`: the OpenAlex lookup itself failed (a bad key, a dropped connection).
- `SKIP`: a JSONL record with no DOI, arXiv or OpenAlex id.

It ends with a count of each and exits with status 1 if any paper was not obtained. Every saved PDF gets a line in `fetch_log.jsonl` in the download folder with status `OK`, the id, the URL it came from (so you can tell a preprint from the published version), the file name and its SHA-256. Every `MANUAL` paper gets a line there too, with its title and landing URL, so the list of papers to download by hand outlives the terminal.

It skips DOIs already in the `sources` table, and file names end in a short hash of the DOI so two papers with the same author, year and title words don't overwrite each other. Dropped connections, timeouts, cut-off responses and HTTP 429/5xx are retried, for API calls and PDF downloads alike.

## Ranking output

`runs/<date>_<time>_<name>_rank.csv` has one row per paper, sorted by `fused_rank`, which combines only the queries listed in `fuse`; each query also has its own `_rank` and `_score` columns. The `<query>_pages` columns give the pages that were scored, which is a sensible place to start reading. Paper ids are the `sources` key or the file name; two files with the same name become `Name` and `Name-2`. An id that starts with `=`, `+`, `-` or `@` gets a `'` in front in the CSV, so a spreadsheet does not run it as a formula.

`runs/<date>_<time>_<name>_rank_run.json` records the question, queries, fuse list, models, parameters, each paper's id, path and SHA-256, token usage, the paper-lector commit and the versions of Python, numpy, tokenizers, pdftotext and the tokenizer, so the run can be repeated.

Runs are never overwritten:

- `rank.py` stops if any output of that `--out` already exists (also a CSV left by a run that crashed before writing `_rank_run.json`), and so does a run whose question, queries or fuse list differ from the saved run. One `--out` holds the runs of one queries `name`: a run of another name, or a record from before the `_rank` names (`<out>_run.json`), stops it too.
- Each finished run adds a line to the project's `questions.jsonl` (time, question, queries file and hash, fuse list, provider, output). There is one per project: beside the config's `queries` file, else in `<project>/queries/`; with no config, beside the queries file given. The queries file is recorded relative to the log's folder (`../old/q.json` for a file elsewhere), so a file is known by where it is, from any working folder. An older `questions.jsonl` beside a queries file is still read. The same question under another name is refused across the whole project; a queries file edited after it was ranked is refused, so write revised queries to a new file.
- While a run is going, `<out>_<name>_rank_run.lock` keeps a second run from using the same `--out`; if a run is killed, the lock stays, and the error says to delete it.

`rank.py` refuses to call the API if the estimate is above `--budget` (15M tokens by default). The estimate is an upper bound computed before any call: every window, the queries, and each rerank package with its abstract, page labels and query. `--budget` checks that estimate; it does not meter the run as it goes. Voyage embeddings are cached in `~/.cache/paper-lector/embeddings.sqlite` after each batch, so a rerun, or a run restarted after a crash, pays only for new text; the estimate still counts everything. The cache is shared by every project on the machine. Table `emb` holds the vectors under a SHA-256 of model, input type and text; table `src` says where each came from: `kind` (`document` or `query`), `ref` (the PDF's SHA-256, or the queries hash as in `questions.jsonl`), `part` (window number in that PDF, or query id), `pages`, `tokens` and `first_seen`. A text met in two PDFs has one vector and two `src` rows. Rows are added for cached vectors too, so vectors from runs before `src` existed get theirs when the same text comes again; vectors no later run meets stay without one.

## Problem papers

Both the dry run and `_rank_run.json` report two kinds of problem paper:

- PDFs with no extractable text (scanned images or protected files), and PDFs on which `pdftotext` fails or runs longer than 5 minutes, are skipped and listed under `corpus.skipped` with the reason. Partial text from a failed extraction is never ranked. They are missing from the order; run OCR on them or read them yourself. A `--ids` run stops if any listed paper has no text, since its frozen corpus would be incomplete.
- Byte-identical copies of a PDF are skipped with a note. Papers whose abstracts share most of their words (often a preprint and its published version) are ranked both times and listed under `corpus.possible_duplicates`. Move one copy out of `pdf_dirs` and rerun into a new `--out`.

## How ranking works

1. `pdftotext` extracts the whole PDF. The bibliography is cut when a References heading in the second half is followed by citation entries, or, with no heading (APS and Nature styles), from the first entry in the second half that opens a list numbered 1, 2, 3, ... in order (`[n]` or `n.`) whose entries nearly all hold a year, so numbered paragraphs or steps are never taken for references; appendices and supplementary material after it stay.
2. The text is split into 1,200-token windows with 200 tokens of overlap, each labelled with the PDF pages it covers. The reranker reads the paper's abstract first (step 4), so windows leave out the abstract's text, or the first 1,000 tokens when no abstract heading is found; title and authors stay. Without this, the first window would repeat the abstract in about four of ten packages (measured on `examples/litsearch-eval`). When the abstract comes from `--abstracts`, the windows keep the opening if the PDF had no abstract heading, and keep the PDF's abstract if the search abstract holds fewer than 90% of its words (another version, or a cut abstract), so text found only in the PDF is still read. A trimmed window's page label and its overlap with other windows (step 3) count only the text it kept.
3. For each paper and query, windows are ordered by Reciprocal Rank Fusion (RRF, below) of their rank by `voyage-4-large` cosine similarity and their rank by BM25 on the query's keyword string. The best 3 are kept, with at most 20% overlap between any two. This step only picks what the reranker reads; it does not rank papers. Before any API call, `rank.py` checks that every query and document pair fits `rerank-3`'s 32,000 tokens; if one does not (usually an overlong abstract in a search record), it stops and names the paper.
4. `rerank-3` scores each paper once per query on its abstract (from `--abstracts` when the paper is in the search results, else read from the PDF, else its first 1,000 tokens) plus those 3 windows. These scores give the per-query ranks (`Q0_main_rank`, ...).
5. `fused_rank` is RRF over the queries in `fuse`.

RRF adds up reciprocal ranks with k = 60 (Cormack, Clarke and Büttcher, SIGIR 2009):

$$\text{fused score}(d) = \sum_{q \in \text{fuse}} \frac{1}{60 + \text{rank}_q(d)}$$

A paper ranked 3rd, 3rd, 1st and 4th on four fused queries scores 1/63 + 1/63 + 1/61 + 1/64 = 0.063764. Ranks are summed rather than scores because reranker scores sit on different scales from one query to the next; the price is that a large score gap and a small one count the same. Tied scores share the better rank. The window choice in step 3 uses the same formula over two ranks, cosine and BM25 (a window with no keyword match gets no BM25 term). The `dense` variant drops BM25 from step 3; the `local` provider replaces the embeddings in step 3 with the local model and the reranker in step 4 with that model's cosine.

BM25 statistics depend on the whole collection, so after adding PDFs rerank everything rather than only the new files.

With `--abstracts`, `rerank-3` also scores every paper on its abstract alone, so papers whose PDF you could not get still get a place in an order. That order is kept apart from the full-text one. On 16 papers of one search, abstract-only scores were 0.06 lower than full-text scores on average, so a paper ranked on its abstract among full-text papers fell 3 to 5 places (up to 12) for lack of a PDF. Ranked against each other on abstracts alone, the same papers kept much of the full-text order (rank correlation 0.76 to 0.88 per query).

## PDFs in other languages

`rank.py` finds abstract, introduction, bibliography and appendix headings in English, Turkish, German, French, Spanish, Italian, Portuguese and Russian (for example *Özet*, *Zusammenfassung*, *Résumé*, *Kaynaklar*, *Références*, *Литература*). Numbered reference lines with a year also count as a bibliography. In other languages it falls back to the first 1,000 tokens and keeps the bibliography; the dry run shows this as `-` in the `abs` and `bib` columns.

`voyage-4-large`, `rerank-3` and the local model are multilingual, so the English `text` of each query works on those papers as it is. BM25 matches words, so add the other language's terms to `keywords` next to the English ones (`energy routing enerji yönlendirme`). BM25 tokenises on Unicode letters and drops Turkish stop words. Chinese, Japanese and Korean text has no spaces between words and BM25 does not work on it; use the `voyage` provider for those papers (the local model's tokenizer reads them, but this has not been tested).

## Script options

| Script | Option | What it does |
| --- | --- | --- |
| `openalex_search.py` | `--semantic TEXT` | Meaning-based search; at most 50 results and not reproducible |
| | `--exact QUERY` | Boolean query on title and abstract, unstemmed (`schedul*` for scheduling and schedules); all pages with `OPENALEX_API_KEY`, the first 200 without; a query OpenAlex would misread or refuse (OR mixed with AND or adjacency at one level, an empty group or empty quotes, an operator with no term, NOT NOT, lower-case and/or/not, `*` or `?` inside quotes when there is more than one term, brackets more than 10 deep, more than 5 operators) is refused before sending; `--out` must be a new `.jsonl` file, reserved before the search so two runs never write the same file; writes the query and counts beside it, with `.query.json` in place of `.jsonl` (`runs/x.jsonl` gives `runs/x.query.json`). The same query on the same OpenAlex snapshot gives the same list |
| | `--cites ID` / `--refs ID` | Works citing ID, or all works ID references (DOI, arXiv id or OpenAlex W id) |
| | `--out FILE` | JSONL output, one work per line, with abstract, PDF link and `in_sources`. Default: `runs/<date>_<time>_<name>_<mode>_search.jsonl` next to the config (mode is `exact`, `semantic`, `cites` or `refs`), with `-2` added when that minute is taken |
| | `--name NAME` | Topic name in the default file name, the same short name the queries file will carry (lowercase, hyphens, at most 25 characters). Without it the file is `<date>_<time>_<mode>_search.jsonl` |
| | `--max N` | Stop after N records (0 = all) |
| `search_overlap.py` | `FILE FILE ...` | Works per search file, shared works and the distinct total (same OpenAlex id, DOI or arXiv id); with a keyword and a semantic file (mode read from `.query.json`), the share of semantic works the keyword file holds, `LOW OVERLAP` under half, and the titles found only by semantic |
| `fetch_pdf.py` | `ID ...` | Fetch the listed works (DOI, arXiv id or OpenAlex W id, also as doi.org or arxiv.org URLs) |
| | `--from FILE` | Fetch every work in a JSONL from `openalex_search.py`; records without any id get a `SKIP` line |
| | `--dest DIR` | Save here instead of `download_dir` |
| `rank.py` | `--setup` | Check `pdftotext`, download the tokenizer, exit |
| | `--out PREFIX` | Output prefix for `_<name>_rank.csv` (or `_<name>_rank-local.csv`, `_<name>_rank-dense.csv`) and `_<name>_rank_run.json`; `<name>` is the queries file's `"name"`, else `paper-lector`. Default: `runs/<date>_<time>` next to the config, with `-2` added when that minute is taken |
| | `--dry` | Build windows, print counts and the token estimate; no API call |
| | `--budget N` | Stop before any API call if the estimate is above N tokens (default 15M) |
| | `--provider voyage\|local` | Override `rank.provider` for this run |
| | `--queries FILE` / `--dirs A,B` | Override `queries` or `pdf_dirs` from the config |
| | `--ids CSV` | Rank exactly the ids in the CSV's `paper` column (frozen corpus). With a `sha256` column (copy it from `corpus.files` in `_rank_run.json`) a changed file under the same id stops the run. An empty list stops it too |
| | `--abstracts FILE[,FILE]` | Search JSONL files: rank every paper on its abstract alone as well (`abs_fused_rank`), including search results with no PDF (`source` = `abstract_only`, listed after the PDFs and named like the PDFs `fetch_pdf.py` saves). Each row also gets a `link` (DOI, else arXiv or OpenAlex), a `citation`, and from the search record `cited_by` (OpenAlex citation count), `cited_pct` (its percentile among works of the same field and year) and `cited_at` (the date they were read; counts grow). When two versions of a paper count as one, the most cited version's numbers are kept. Citations are for reading the list only; they never change a rank. A record is tied to its PDF through the sources DOI, an `OK` line in `fetch_log.jsonl` (the file in that log's own folder, SHA-256 checked) or, failing those, its title: at least 80% of its content words in order in the PDF's first 40 words, and one PDF only. Records whose titles are at least 95% alike (a preprint and its published version) count as one paper. Only a real abstract counts in the abstract order (the search record's, else one under an Abstract heading in the PDF); a paper with neither is listed but unranked. With no PDFs at all, the run gives the abstract order alone, and `--ids` listing only `abstract_only` rows is refused. The two orders are kept apart: abstract-only scores run lower than full-text ones |
| | `--expect A,B` | Paper ids you expect in the first query's top 10, written down before the run |
| | `--variants hybrid,dense` | Add a dense-only ablation (voyage only) |

## Ranking providers

For now, `rank.py` supports one API: Voyage (`voyage-4-large` embeddings and `rerank-3`). Other embedding or rerank services, such as OpenAI, Cohere or a local Ollama model, are not supported yet. Adding one means a new name in `PROVIDERS` in `scripts/common.py`, a matching request and response format in `call()` in `scripts/rank.py`, and its own API key name. If you need one, open an issue.

The `local` provider needs no key and makes no API call (apart from the one-time downloads). It uses [`potion-multilingual-128M`](https://huggingface.co/minishlab/potion-multilingual-128M), a [model2vec](https://github.com/MinishLab/model2vec) model: one fixed vector per token, so a text's vector is the mean of its tokens' vectors, computed with numpy and no neural network at run time. Windows are chosen as in step 3, by RRF of this model's cosine and BM25; each paper is then scored by the cosine between the query `text` and its abstract plus those windows, in place of `rerank-3`. 18 PDFs take a few seconds. The output is `<out>_<name>_rank-local.csv` with the same columns, and `_rank_run.json` records the provider and the model with its revision. Expect a rougher order than voyage: on [`examples/qnet`](examples/qnet), 18 PDFs, its fused order agreed with the voyage run at Spearman 0.56 and its abstract order at 0.64 (BM25 alone, the provider it replaces, gave 0.49 and 0.34). The `bm25` provider is gone; a config that names it stops and asks for `local`.

## Safety

`fetch_pdf.py` keeps a file only if it starts with `%PDF`, never overwrites an existing file, and does not save a download that is byte-identical to a PDF already in the folders. It writes to a temporary file first, so a crash never leaves a half PDF under the final name. It fetches only http(s) URLs whose host resolves to a public address, and checks every redirect the same way, so a URL in OpenAlex data cannot point it at local files, this machine or the local network. The check resolves the name before connecting; a DNS server that answers differently a moment later is not covered. Each download stops at 100 MB, or after 5 minutes counting all retries; a response shorter than its declared length is retried and never saved. It never works around paywalls, logins or bot checks.

The paths in `literature.json` and in the `sources` CSV are trusted: they can point anywhere on disk, and the scripts read what they name. Do not run the scripts on a project config you have not read.

## Tests

The tests run offline: small generated PDFs, sample text with headings in each supported language, a word tokenizer and a fake Voyage API. They need `pdftotext` on `PATH`. One test uses the real tokenizer and is skipped until `rank.py --setup` has run. GitHub Actions runs the suite on every push (`.github/workflows/tests.yml`).
