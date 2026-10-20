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
- [Errors and a full disk](#errors-and-a-full-disk)
- [Platforms](#platforms)
- [Tests](#tests)

## Setup

API keys are looked up in the environment, then the project's `.env`, then `~/.config/paper-lector/.env`. `OPENALEX_API_KEY` is used by search and fetch; without it, keyword and citing searches return only the first 200 works (references and semantic are not cut) and the daily budget is about 100 searches, shared by everyone on the same IP address. `VOYAGE_API_KEY` is used by `rank.py` with the default `voyage` provider.

`rank.py --setup` checks that `pdftotext` is on `PATH` (and prints the install command if not) and downloads the `voyage-4-large` tokenizer from Hugging Face into `~/.cache/paper-lector/`. The tokenizer is pinned to one Hugging Face revision and checked against its SHA-256, so two machines cut the same windows; `requirements.txt` pins the two Python packages and `constraints.txt` every package they pull in, for the same reason (`pip install -r requirements.txt -c constraints.txt`). The `pdftotext` version is not pinned: poppler releases can split text a little differently, which moves window boundaries, so `_rank_run.json` records it. Every rank run needs that tokenizer to cut windows and count tokens, including `--dry` and the `local` provider. `rank.py --setup --provider local` also downloads the local model (`minishlab/potion-science-32M`, 130 MB) into `~/.cache/paper-lector/potion-science-32M/<revision>/`, and with `--local-model retrieval` the other one (`minishlab/potion-retrieval-32M`, 131 MB, into `potion-retrieval-32M/<revision>/`), pinned the same way and checked against its SHA-256 on every load; after that, the `local` provider works fully offline. A local run without the model downloads it first. The tokenizer's file name and the model's folder carry the first 7 characters of their pinned revision, so when a paper-lector update pins a newer one, the next run downloads it beside the old copy instead of stopping on a SHA-256 mismatch; the old file or folder can then be deleted. Before 0.2.0 the local model was `potion-multilingual-128M`; its folder (531 MB) is no longer used and can be deleted. Runs made with different revisions give different scores; `_rank_run.json` records both revisions. If the tokenizer is missing on an offline machine, `rank.py` stops and says where to put the file; an interrupted download leaves no half-written file behind.

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
├── potion-science-32M/<revision>/     the local provider's default model, 130 MB
└── potion-retrieval-32M/<revision>/   the other local model, 131 MB, only with "model": "retrieval"
```

Only `literature.json` has a fixed name among the files you write; the scripts' own logs are always `questions.jsonl` and `fetch_log.jsonl`. The other paths come from it (`pdf_dirs`, `download_dir`, `sources`, `queries`), so another layout works too; this one is what the agent writes for a new project. Search and rank outputs go to `runs/` next to the config unless `--out` says otherwise, and sort by time, so a search and the rank that used it sit together. `runs/` is reproducible from the logs and usually stays out of git, like the PDFs; [`examples/entanglement-scheduling`](examples/entanglement-scheduling) keeps its runs as a worked example.

## Config and queries

All three scripts look for `literature.json` from the current folder up to the project root (the first folder with `.git`); `--config` points to another one. Paths in it are relative to that file.

`rank` is optional; `voyage` is the default provider. An optional `sources` CSV (the papers you already hold, with `key`, `pdf_path` and `doi` columns) can be added too; [`examples/literature.json`](examples/literature.json) shows it. If the CSV is missing, the scripts say so and carry on without it.

The queries file holds the question, an optional short `name` for its output files (lowercase words joined by hyphens, at most 25 characters, kept for every later run of the same question) and a few labelled queries (`main`, `subject`, `approach`, `outcome`, `context`, `comparison`). Each one has a full sentence for the embedding model and the reranker, plus a keyword string for BM25. [`examples/entanglement-scheduling/queries/queries.json`](examples/entanglement-scheduling/queries/queries.json) is a complete file. Keep queries files in a `queries/` folder named after their `name`; the project's `questions.jsonl` (below) sits beside the config's queries file. Once you have seen results from a queries file, don't edit it; write a new file for a revised run.

With an agent, the agent first counts the PDFs in `pdf_dirs`. If a folder is missing or empty, it does not start the questions; it offers to search OpenAlex and download open-access papers, to point to another folder, or to stop. Then it asks seven questions in a fixed order: the six query slots, then which slots to fuse. Each screen holds as many questions as the agent's question tool allows, so Claude Code shows two screens and Codex may show three. For each slot you take the agent's suggestion, type your own wording, or leave it empty (`main` is required). The agent writes the queries from your answers and shows them as a table for you to edit. After you approve them, it freezes the file, runs a dry run to report the token estimate, runs the ranking, and reports the top 10 with the pages to start on.

## Fetching PDFs

`fetch_pdf.py` saves into `download_dir` and prints one line per paper:

- `MANUAL`: it could not get the paper (often a publisher returning 403); download it yourself. When no URL could be reached at all (network down, DNS, timeouts), the paper is an `ERROR` to retry instead.
- `ERROR`: the OpenAlex lookup itself failed (a bad key, a dropped connection).
- `SKIP`: a JSONL record with no DOI, arXiv or OpenAlex id.

arXiv is tried first. The arXiv id comes from the id given, or else from an OpenAlex location whose landing page is on `arxiv.org` or `export.arxiv.org` (`/abs/` or `/pdf/`) or `arxiv-vanity.com/papers/`.

It ends with a count of each and exits with status 1 if any paper was not obtained. Every saved PDF gets a line in `fetch_log.jsonl` in the download folder with status `OK`, the id, the URL it came from (so you can tell a preprint from the published version), the file name, its SHA-256 and, when OpenAlex has the work, its title, authors, year, venue and volume, issue and pages (empty fields left out). Every `MANUAL` paper gets a line there too, with its title and landing URL, so the list of papers to download by hand outlives the terminal. A download byte-identical to a PDF already in the folders is not saved; it gets a `HAVE` line with the id, the URL, that PDF's path relative to the download folder and its SHA-256, plus the same citation fields, so `rank.py` can still tie the id to the PDF.

It skips DOIs already in the `sources` table whose PDF is there (a row whose `pdf_path` is missing is noted and fetched again), and file names end in a short hash of the DOI so two papers with the same author, year and title words don't overwrite each other. Dropped connections, timeouts, cut-off responses and HTTP 429/5xx are retried, for API calls and PDF downloads alike.

## Ranking output

`runs/<date>_<time>_<name>_rank.csv` has one row per paper, sorted by `fused_rank`, which combines only the queries listed in `fuse`; each query also has its own `_rank` and `_score` columns. The reading columns come first: `fused_rank`, `abs_fused_rank` (with `--abstracts`), `citation`, `link`, `cited_by`, `cited_pct` and `start_pages`; every other column follows in the order below, none dropped. Rows are read by column name, so scripts that read the CSV keep working. `citation` (authors, up to six and then "et al.", year, title, venue, volume(issue), pages) and `link` (DOI, else arXiv or OpenAlex page) come from the search record with `--abstracts`, else from the sources table's DOI (link only), else from the PDF's `OK` or `HAVE` line in `fetch_log.jsonl`; a PDF none of these names gets both empty. Lines written before fetches stored the citation fields give the link only. Citations are for reading the list only; they never change a rank.

`start_pages` gives up to three page ranges to start reading at. Each `fuse` query's `<query>_pages` cell is one vote per range; the ranges with the most votes come first, ties go to the earlier page, and a range that overlaps one already chosen (sharing a page, as `p. 4-5` and `p. 5-6` do) is skipped, never widened. A paper with no PDF, or with fewer distinct ranges, gets fewer. The `<query>_pages` columns give the pages scored for every query, `fuse` or not, each range once: two windows with the same page label show as one. Paper ids are the `sources` key or the file name; two files with the same name become `Name` and `Name-2`. Every text cell (the paper id, the citation and the rest) that starts with `=`, `+`, `-`, `@`, a tab, a line break or `'` gets a `'` in front in the CSV, so a spreadsheet does not run it as a formula and two different ids never look the same; `--ids` reads such ids back.

`runs/<date>_<time>_<name>_rank_run.json` records the question, queries, fuse list, models, parameters, each paper's id, path (relative to the project) and SHA-256, token usage, the command line (`argv`), the working folder (`cwd`), the paper-lector version and commit (`git describe`, with `-dirty` when any tracked file of the paper-lector checkout differs from that commit), the operating system, the versions of Python, numpy, tokenizers, pdftotext and the tokenizer, and under `inputs` the SHA-256 of the queries file, the config, the sources table and every `fetch_log.jsonl`: everything besides the PDFs that can change a row. With the same files, a `local` run gives the same CSV byte for byte. Voyage serves `voyage-4-large` and `rerank-3` under fixed names that it may update, so a voyage rerun can differ slightly.

Runs are never overwritten:

- `rank.py` stops if any output of that `--out` already exists (also a CSV left by a run that crashed before writing `_rank_run.json`), and so does a run whose question, queries or fuse list differ from the saved run. One `--out` holds the runs of one queries `name`: a run of another name, or a record from before the `_rank` names (`<out>_run.json`), stops it too.
- Each finished run adds a line to the project's `questions.jsonl` (time, question, queries file and hash, fuse list, provider, output). There is one per project: beside the config's `queries` file, else in `<project>/queries/`; with no config, beside the queries file given. The queries file is recorded relative to the log's folder (`../old/q.json` for a file elsewhere), so a file is known by where it is, from any working folder. An older `questions.jsonl` beside a queries file is still read. The same question under another name is refused across the whole project; a queries file edited after it was ranked is refused, so write revised queries to a new file.
- While a run is going, `<out>_<name>_rank_run.lock` keeps a second run from using the same `--out`; if a run is killed, the lock stays, and the error says to delete it.

`rank.py` refuses to call the API if the estimate is above `--budget` (15M tokens by default). The estimate is an upper bound computed before any call: every window, the queries, and each rerank package with its abstract, page labels and query. `--budget` checks that estimate, and it also meters the run: every request to Voyage counts its tokens against the budget before it is sent, retries included (a request whose answer was lost on the way back may still be billed), and the run stops before a request that would pass it. Voyage embeddings are cached in `~/.cache/paper-lector/embeddings.sqlite` after each batch, so a rerun, or a run restarted after a crash, does not pay for them again. Reranking is not cached and is paid in full on every run. On the entanglement-scheduling example (73 PDFs, 147 abstracts) a first run sends about 3.1M tokens, 1.55M for embeddings and 1.57M for reranking, under the estimate of 3.19M; a rerun of the same files sends the 1.57M of reranking again. The estimate counts everything, cached or not. The cache is shared by every project on the machine. Table `emb` holds the vectors under a SHA-256 of model, input type and text; table `src` says where each came from: `kind` (`document` or `query`), `ref` (the PDF's SHA-256, or the queries hash as in `questions.jsonl`), `part` (window number in that PDF, or query id), `pages`, `tokens` and `first_seen`. A text met in two PDFs has one vector and two `src` rows. Rows are added for cached vectors too, so vectors from runs before `src` existed get theirs when the same text comes again; vectors no later run meets stay without one.

## Problem papers

Both the dry run and `_rank_run.json` report two kinds of problem paper:

- PDF files are found by extension in any case (`.pdf`, `.PDF`). A `sources` row whose `pdf_path` does not exist gets a note; a copy of that PDF in `pdf_dirs` is then ranked under its file name, without the sources DOI. A `download_dir` outside every `pdf_dirs` folder is ranked too, with a note, so a fetched PDF is never left out.
- PDFs with no extractable text (scanned images or protected files, or a scan of three or more pages whose only text is a line every page repeats, such as a publisher's download notice), and PDFs on which `pdftotext` fails or runs longer than 5 minutes, are skipped and listed under `corpus.skipped` with the reason. Partial text from a failed extraction is never ranked. They are missing from the order; run OCR on them or read them yourself. A `--ids` run stops if any listed paper has no text, since its frozen corpus would be incomplete.
- Byte-identical copies of a PDF are skipped with a note. Papers whose abstracts share most of their words (often a preprint and its published version) are ranked both times and listed under `corpus.possible_duplicates`. Move one copy out of `pdf_dirs` and rerun into a new `--out`.

## How ranking works

1. `pdftotext` extracts the whole PDF; ligature characters (`ﬁ`, `ﬂ`, ...) become plain letters. Every bibliography is cut: from a References heading followed by citation entries (numbered, author-year as in ACL and APA, or alphabetic keys such as `[Aco+24]`), wherever it sits (a long appendix can put it in the first half; a thesis can have one per chapter), or, with no heading (APS and Nature styles), from an entry past the first fifth of the text that opens a list numbered 1, 2, 3, ... in order (`[n]`, `n.`, or `n A.` when pdftotext dropped the bracket) whose entries nearly all hold a year and mostly name an author (an initial, "Surname AB," or "et al.") or a venue, so numbered paragraphs, algorithm lines or steps, dated ones too, are not taken for references. pdftotext does not always keep a two-column page in order, so a cut starts at the entry `[1]` when body text sits between it and the heading, starts at the list when the heading lies up to 4,500 characters away from it, and also takes the entries printed just above the heading. Each cut ends where the entries stop: at an appendix heading (the word, or a letter and a short title such as "A Models Set-Up" that thin text follows), or at the first 1,500 characters with fewer than 3 publication years in them, the years of in-text citations such as "(Liu et al., 2020)" not counted (a single such stretch between two dense ones is a gap inside the list). A list numbered on after an appendix page is cut too. Appendices and whatever pdftotext placed after the list (a conclusion, a figure) stay. Page labels after a cut still give the PDF's pages.
2. The text is split into 1,200-token windows with 200 tokens of overlap, each labelled with the PDF pages it covers. The reranker reads the paper's abstract first (step 4), so windows leave out the abstract's text (the title and authors before it stay), or the first 1,000 tokens, title included, when no abstract heading is found. An abstract is the text after an Abstract heading at the start of a line ("A BSTRACT" in the ICLR template too), up to an Introduction heading or an Index Terms, Keywords or CCS Concepts line, 100 to 4,000 characters. Without this, the first window would often repeat the abstract. When the abstract comes from `--abstracts`, the windows keep the opening if the PDF had no abstract heading, and keep the PDF's abstract if the search abstract holds fewer than 90% of its words (another version, or a cut abstract), so text found only in the PDF is still read. A trimmed window's page label and its overlap with other windows (step 3) count only the text it kept.
3. For each paper and query, windows are ordered by Reciprocal Rank Fusion (RRF, below) of their rank by `voyage-4-large` cosine similarity and their rank by BM25 on the query's keyword string. The best 3 are kept, any two sharing less than 20% of the smaller one's tokens. This step only picks what the reranker reads; it does not rank papers. Before any API call, `rank.py` checks that every query and document pair fits `rerank-3`'s 32,000 tokens; if one does not (usually an overlong abstract in a search record), it stops and names the paper.
4. `rerank-3` scores each paper once per query on its abstract (from `--abstracts` when the paper is in the search results, else read from the PDF, else its first 1,000 tokens) plus those 3 windows. These scores give the per-query ranks (`Q0_main_rank`, ...).
5. `fused_rank` is RRF over the queries in `fuse`.

RRF adds up reciprocal ranks with k = 60 (Cormack, Clarke and Büttcher, SIGIR 2009):

$$\text{fused score}(d) = \sum_{q \in \text{fuse}} \frac{1}{60 + \text{rank}_q(d)}$$

A paper ranked 3rd, 3rd, 1st and 4th on four fused queries scores 1/63 + 1/63 + 1/61 + 1/64 = 0.063764. Ranks are summed rather than scores because reranker scores sit on different scales from one query to the next; the price is that a large score gap and a small one count the same. Tied scores share the better rank. Choosing `fuse`: on LitSearch questions, each aimed at one paper, voyage with `main` alone beat `main` + `subject` with one set of blind `subject` sentences (MRR +0.12 on 46 questions, 40 PDFs each) and tied with another (−0.01, 95% interval −0.07 to +0.05, on 48 questions, 20 PDFs each), so the default stays `main` + `subject` (`examples/litsearch/MINI-TEST.md`). The window choice in step 3 uses the same formula over two ranks, cosine and BM25 (a window with no keyword match gets no BM25 term). The `dense` variant drops BM25 from step 3; the `local` provider replaces the embeddings in step 3 with the local model and the reranker in step 4 with that model's cosine.

BM25 statistics depend on the whole collection, so after adding PDFs rerank everything rather than only the new files.

With `--abstracts`, `rerank-3` also scores every paper on its abstract alone, so papers whose PDF you could not get still get a place in an order. That order is kept apart from the full-text one. On 16 papers of one search (an earlier run, not kept in the repo), abstract-only scores were 0.06 lower than full-text scores on average, so a paper ranked on its abstract among full-text papers fell 3 to 5 places (up to 12) for lack of a PDF. Ranked against each other on abstracts alone, the same papers kept much of the full-text order (rank correlation 0.76 to 0.88 per query).

## PDFs in other languages

`rank.py` finds abstract, introduction, bibliography and appendix headings in English, Turkish, German, French, Spanish, Italian, Portuguese and Russian (for example *Özet*, *Zusammenfassung*, *Résumé*, *Kaynaklar*, *Références*, *Литература*). Numbered reference lines with a year also count as a bibliography. In other languages it falls back to the first 1,000 tokens, and a bibliography stays unless it is a numbered list of dated entries, which is cut in any language; the dry run shows this as `-` in the `abs` and `bib` columns.

`voyage-4-large` and `rerank-3` are multilingual, so the English `text` of each query works on those papers as it is. The local models are English only; for papers in other languages use the `voyage` provider. BM25 matches words, so add the other language's terms to `keywords` next to the English ones (`energy routing enerji yönlendirme`). BM25 tokenises on Unicode letters and drops Turkish stop words. Chinese, Japanese and Korean text has no spaces between words and BM25 does not work on it; use the `voyage` provider for those papers.

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
| `fetch_pdf.py` | `ID ...` | Fetch the listed works (DOI, arXiv id or OpenAlex W id, also as doi.org or arxiv.org URLs; an arXiv version such as `v2` is dropped, since arXiv DOIs carry none) |
| | `--from FILE` | Fetch every work in a JSONL from `openalex_search.py`; records without any id get a `SKIP` line |
| | `--dest DIR` | Save here instead of `download_dir` |
| `rank.py` | `--setup` | Check `pdftotext`, download the tokenizer (with `--provider local` also the local model, `--local-model` picks which), exit |
| | `--out PREFIX` | Output prefix for `_<name>_rank.csv` (or `_<name>_rank-local.csv`, `_<name>_rank-dense.csv`) and `_<name>_rank_run.json`; `<name>` is the queries file's `"name"`, else `paper-lector`. Default: `runs/<date>_<time>` next to the config, with `-2` added when that minute is taken |
| | `--dry` | Build windows, print counts and the token estimate; no API call |
| | `--budget N` | Stop before any API call if the estimate is above N tokens (default 15M) |
| | `--provider voyage\|local` | Override `rank.provider` for this run |
| | `--local-model science\|retrieval` | Override `rank.model` for this run; local provider only (default `science`) |
| | `--queries FILE` / `--dirs A,B` | Override `queries` or `pdf_dirs` from the config |
| | `--ids CSV` | Rank exactly the ids in the CSV's `paper` column (frozen corpus). With a `sha256` column (copy it from `corpus.files` in `_rank_run.json`) a changed file under the same id stops the run. An empty list stops it too |
| | `--abstracts FILE[,FILE]` | Search JSONL files: rank every paper on its abstract alone as well (`abs_fused_rank`), including search results with no PDF (`source` = `abstract_only`, listed after the PDFs and named like the PDFs `fetch_pdf.py` saves, surname, year and title words, but without its hash; `-2` is added when two share a name). Each row also gets a `link` (DOI, else arXiv or OpenAlex), a `citation`, and from the search record `cited_by` (OpenAlex citation count), `cited_pct` (its percentile among works of the same field and year) and `cited_at` (the date they were read; counts grow). When two versions of a paper count as one, the most cited version's numbers are kept. Citations are for reading the list only; they never change a rank. A record found twice (in two search files) is one record: the first one's fields win and the later one fills the empty ones, such as a missing abstract. A record is tied to its PDF through the sources DOI, an `OK` or `HAVE` line in `fetch_log.jsonl` (the file in that log's own folder, or a byte-identical PDF ranked in its place; SHA-256 checked) or, failing those, its title: at least 80% of its content words in order in the PDF's first 40 words, and one PDF only. A record whose ids name two PDFs (a preprint and its published version, both held) goes to the one its DOI names, with a note. Records count as one paper when their titles are at least 95% alike with the same numbers ("Part I" and "Part II" stay apart) and, where both records give them, the first authors' names share a word (so "Angela Sara Cacciapuoti" and "CACCIAPUOTI, Angela Sara" match) and the years are at most two apart (two papers that only share a title stay apart), or when a version was retitled: the same first author, years at most one apart, titles at least 85% alike and abstracts sharing 80% of their words. The abstract order scores the abstract alone, without the title, for every paper alike. Only a real abstract counts in the abstract order (the search record's, else one under an Abstract heading in the PDF); a paper with neither is listed but unranked. With no PDFs at all, the run gives the abstract order alone, and `--ids` listing only `abstract_only` rows is refused. The two orders are kept apart: abstract-only scores run lower than full-text ones |
| | `--expect A,B` | Paper ids you expect in the first query's top 10, written down before the run |
| | `--variants hybrid,dense` | Add a dense-only ablation (voyage only) |

## Ranking providers

Besides the `local` provider below, `rank.py` supports one API: Voyage (`voyage-4-large` embeddings and `rerank-3`). Other embedding or rerank services, such as OpenAI, Cohere or an Ollama model, are not supported yet. Adding one means a new name in `PROVIDERS` in `scripts/common.py`, a matching request and response format in `call()` in `scripts/rank.py`, and its own API key name. If you need one, open an issue ([`CONTRIBUTING.md`](CONTRIBUTING.md)).

The `local` provider needs no key and makes no API call (apart from the one-time downloads). It uses [`potion-science-32M`](https://huggingface.co/minishlab/potion-science-32M), an English [model2vec](https://github.com/MinishLab/model2vec) model, or with `"rank": {"provider": "local", "model": "retrieval"}` (or `--local-model retrieval`) [`potion-retrieval-32M`](https://huggingface.co/minishlab/potion-retrieval-32M): one fixed vector per token, so a text's vector is the mean of its tokens' vectors, computed with numpy and no neural network at run time. Windows are chosen as in step 3, by RRF of this model's cosine and BM25; each paper is then scored by the cosine between the query `text` and its abstract plus those windows, in place of `rerank-3`. 73 PDFs take about 25 seconds. The output is `<out>_<name>_rank-local.csv` with the same columns, and `_rank_run.json` records the provider and the model with its revision. Expect a rougher order than voyage: on [`examples/entanglement-scheduling`](examples/entanglement-scheduling), 73 PDFs, the science model's fused order agreed with the voyage run at Spearman 0.79 and its abstract order (139 papers) at 0.78, the retrieval model's at 0.81 and 0.75, and the top 10s shared 5 and 4 papers with Voyage's (README, step 5). Science is the default because it kept Voyage's top 10 higher (none below 26th; retrieval 35th). The earlier default, `potion-multilingual-128M`, gave 0.70 and 0.71 on the same PDFs (the run in version 0.1.0, commit `ea3cd4d`); it was replaced because both English models agree more closely and are a quarter of its size, at the cost of PDFs in other languages. The `bm25` provider is gone; a config that names it stops and asks for `local`.

## Safety

`fetch_pdf.py` keeps a file only if it starts with `%PDF`, never overwrites an existing file, and does not save a download that is byte-identical to a PDF already in the folders. It writes the whole file to a temporary name first and links it into place, so a crash or a full disk never leaves a half PDF under the final name. On a drive with no hard links (FAT, exFAT, some network or synced folders) it renames the temporary file into place after checking that the name is still free; only a second fetch writing the same file at that instant could then replace it. It fetches only http(s) URLs whose host resolves to a public address (a NAT64 address, `64:ff9b::/96`, is judged by the IPv4 address inside it), and checks every redirect the same way, so a URL in OpenAlex data cannot point it at local files, this machine or the local network. The check resolves the name before connecting; a DNS server that answers differently a moment later is not covered. Each download stops at 100 MB, or after 5 minutes counting all retries and a last read that stalls (the name lookup before it is not counted); a response shorter than its declared length is retried and never saved. It never works around paywalls, logins or bot checks.

API keys are only ever sent in a request header, one that is not passed on when a server redirects the request elsewhere, and paper-lector never writes them into a log, a CSV or a run record. When an error message quotes a server's answer, a key in it is replaced by `***`. When a key comes from a `.env` file that other users can read, the scripts print a note with the `chmod 600` that fixes it.

The paths in `literature.json` and in the `sources` CSV are trusted: they can point anywhere on disk, and the scripts read what they name. Do not run the scripts on a project config you have not read.

## Errors and a full disk

Every script stops with a one-line message, and keeps no partial output, when:

- the network is down or a server keeps failing after the retries (OpenAlex, Voyage); `fetch_pdf.py` stops after 3 papers in a row reach no server, saying how many were not tried;
- Voyage keeps answering HTTP 429 (rate limit; accounts with no payment method get very low limits);
- a key is refused (`OPENALEX_API_KEY is wrong`, `Voyage refused the key`);
- Voyage answers with a rerank result that misses a document or holds a score that is not a number, or with an embedding that is missing, zero, not finite or of the wrong size (it is never cached; a cached vector of another size is fetched again, with a note);
- the embedding cache cannot be read or written (a full disk);
- the config is not a JSON object, a file named on the command line is missing, or a search file, `--abstracts` file, `questions.jsonl` or `fetch_log.jsonl` has a line that is not a JSON object (the message names the file and line; `search_overlap.py` too);
- the disk is full.

`rank.py` builds its CSVs and run record in memory and writes them at the end, each to a temporary file first; if any write fails, it removes the ones it already wrote, and if the line in `questions.jsonl` cannot be added, it removes the outputs too and cuts the log back to its old length. `openalex_search.py` removes both reserved files. `fetch_pdf.py` removes a PDF whose `fetch_log.jsonl` line could not be written and stops, keeping the PDFs saved before it with their lines. Embeddings already received stay in the cache, so running the same command again pays only for the rest.

## Platforms

macOS and Linux are supported, and CI runs the tests on both (`ubuntu-latest` and `macos-latest`). Windows is not tested or supported: the commands in the README and in `SKILL.md` use a Unix shell (`.venv/bin`, `ln -s`, `read -s`). Use WSL there. `pdftotext` is called with `-enc UTF-8` and read as UTF-8 whatever the locale, so accented and non-Latin text comes through the same on every system.

## Tests

The tests run offline: small generated PDFs, sample text with headings in each supported language, a word tokenizer, a fake Voyage API and a fake local model. They need `pdftotext` on `PATH`. Four tests use the real tokenizer or a local model and are skipped until `rank.py --setup --provider local` (and `--local-model retrieval` for the retrieval model) has run; one of them is a first run as a new user makes it, end to end with no fakes. GitHub Actions runs the suite on every push on Ubuntu and macOS (`.github/workflows/tests.yml`), from a clean install with `constraints.txt`, after `rank.py --setup --provider local` for both models; there `PAPER_LECTOR_REQUIRE_MODELS=1` makes those tests run instead of skipping (a missing model is then downloaded by the test, or the test fails when offline). The failure paths above (full disk, bad answers, retries against the budget, broken files, no hard links) have their own tests in `tests/test_failures.py`.
