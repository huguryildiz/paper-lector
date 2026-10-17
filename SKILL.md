---
name: paper-lector
description: Search OpenAlex, download open-access PDFs, and rank a researcher's own PDF collection against frozen research-question queries, giving a reading order with the pages to start on. Use for a literature search, a citation chase, fetching papers' PDFs, or "which of my PDFs should I read first for this question". It gives reading leads, not evidence, and does not answer questions or write reviews.
---

# paper-lector

Ranks research PDFs and suggests starting pages; reading leads, not evidence.

```bash
PL=~/.claude/skills/paper-lector
PY=$PL/.venv/bin/python        # arm64 venv with numpy and tokenizers; pdftotext must be on PATH
```

| Step | Command | Output |
| --- | --- | --- |
| Search | `$PY $PL/scripts/openalex_search.py --exact '<query>' --out <file>.jsonl` | one JSON line per work: abstract, open-access PDF link, `in_sources` |
| Fetch | `$PY $PL/scripts/fetch_pdf.py --from <file>.jsonl` or `... fetch_pdf.py <doi> <arxiv id>` | PDFs in `download_dir`; `MANUAL` lines for the rest |
| Rank | `$PY $PL/scripts/rank.py --out <prefix> --dry`, then without `--dry` | `<prefix>_hybrid.csv` and `<prefix>_run.json` |

Write outputs outside the project's tracked files (a scratch or `runs/` folder) unless the user asks to keep them.

## Step 1: the project config

Every script looks for `literature.json`, starting in the current folder and walking up to the project root (the first folder with `.git`). Paths in it are relative to its own folder.

```json
{
  "pdf_dirs": ["literature/pdfs"],
  "download_dir": "literature/pdfs/new",
  "sources": "literature/sources.csv",
  "queries": "literature/queries.json",
  "rank": {"provider": "voyage"}
}
```

- `pdf_dirs` (required): folders searched recursively for PDFs.
- `download_dir`: where `fetch_pdf.py` saves; defaults to the first `pdf_dirs` entry.
- `sources` (optional): a CSV with `key`, `pdf_path` and `doi` columns. Papers listed there keep their key as id; other PDFs are named by file stem.
- `queries`: the frozen queries file for `rank.py`.
- `rank` (optional): `{"provider": "voyage"}` (default) or `{"provider": "bm25"}`. `--provider` overrides it for one run.

If there is no `literature.json`, ask the user once where their PDFs are, then write the file. Do not guess.

Keys: `OPENALEX_API_KEY` (search, fetch) and `VOYAGE_API_KEY` (rank, voyage provider only) are read from the environment, then the project `.env`, then `~/.config/paper-lector/.env`. Never put a key on a command line, in chat or in any other file.

## Step 2: writing the queries

Settle the research question before drafting any query. Suggest 2 or 3 candidate questions, each one neutral sentence, built from the user's request and what the project already holds (the topic they named, the titles in `sources` or the PDF folders, an existing `queries.json`). Ask with the AskUserQuestion tool: one option per candidate, recommended one first; the tool's free-text "Other" lets the user write their own. Without that tool, list the candidates numbered and ask the user to pick one or type their own. Use the chosen or written question word for word; if the user edits a candidate, the edited text wins. It becomes the `question` field and the `main` slot.

Six labels, all optional except `main`:

| Label | Asks | Example (which user gets an ageing entangled pair) |
| --- | --- | --- |
| `main` | The whole question in one neutral sentence; no hoped-for result | Which competing request should receive an ageing stored entangled pair? |
| `subject` | What is studied: system, population, phenomenon, material, model | Quantum switch with memories and waiting requests |
| `approach` | What is done: method, intervention, design, algorithm, procedure | Service discipline, scheduling policy |
| `outcome` | What is measured or concluded: metric, effect, performance, property | Age of entanglement, fidelity, cost |
| `context` | Where or under which conditions | Underwater links, delayed control |
| `comparison` | Alternatives or baselines | First-come-first-served, random choice |

Then fill the other five slots the same way, on question screens, before writing any query text. One AskUserQuestion call takes at most 4 questions, so use two calls:

1. `subject`, `approach`, `outcome`, `context`.
2. `comparison`, then the `fuse` choice (multiSelect over the filled slots, `main` + `subject` marked recommended).

Each slot question names the slot and what it asks, for example "approach: what is done (method, intervention, design, algorithm)?", with header = the label. Options: one or two suggestions drawn from the question, written like the example column (a short phrase, recommended first, the description saying why it fits), plus "Leave empty". The tool's free-text "Other" takes the user's own wording, which is used as given. Without the tool, ask the same questions in chat, one numbered list per slot.

From the answers, write each slot's `text` and `keywords` by the rules below, show the finished set as one table, and freeze the file only after the user approves it. Never change a frozen file after seeing results; a revision is a new file and a new run.

Rules for drafting:

- Each `text` is one English sentence of about 20 to 50 words; each `keywords` is a short BM25 string of the same meaning.
- Spread the vocabularies of neighbouring fields across the set (for example queueing: service discipline, LIFO, buffer; decision theory: policy, Markov decision process). A relevant paper may use another field's words.
- Put the decision ("which X") in `main`. Do not put a solver in `approach` unless the user intends it.
- Leave a slot empty rather than padding it. Use two queries with the same label if one slot really needs two angles.
- `fuse` lists the query ids combined into `fused_rank`. Default: the non-empty `main` and `subject`; the user's choice on the fuse screen overrides it. `context` and `comparison` are often better read on their own columns.

```json
{
  "question": "Which user should receive an ageing stored entangled pair?",
  "fuse": ["Q0", "Q1"],
  "queries": {
    "Q0": {"label": "main", "description": "core question", "text": "...", "keywords": "..."},
    "Q1": {"label": "subject", "description": "...", "text": "...", "keywords": "..."}
  }
}
```

If the user names papers they expect near the top, write them down with the query they should match before the run (`--expect`). They are a sanity check, not a test, once their ranks have been seen.

## Step 3: ranking

1. Run `rank.py --out <prefix> --dry`. It prints counts per paper (tokens, windows, bibliography cut, abstract found) and the token estimate, with no API call. Report the estimate.
2. Run without `--dry`. It stops before any API call if the estimate is above `--budget` (15M tokens by default). Voyage gives 200M free tokens per model; after that `voyage-4-large` costs $0.12 and `rerank-3` $0.05 per million tokens.
3. Report the fused top 10, where it disagrees with single queries, and the sanity check result as it is.

What happens inside: the whole PDF is split into 1,200-token windows with page labels (bibliography cut when found with confidence; appendices kept). For each paper and query, the 3 best windows are chosen by fusing embedding similarity (`voyage-4-large`) with BM25 on the keyword string. The reranker (`rerank-3`) then scores each paper once per query on its abstract plus those 3 windows. Adding PDFs changes BM25 statistics, so rerun the whole collection rather than ranking only the new files.

Output columns: `paper`, `fused_rank`, `fused_score`, then per query `<id>_<label>_rank`, `_score` and `_pages` (the pages the reranker read, a place to start reading), then `tokens`, `bib_cut`, `abstract_found`. `<prefix>_run.json` records the question, queries, fuse list, models, parameters, corpus ids, token usage and the paper-lector commit.

**No Voyage key.** If `VOYAGE_API_KEY` is missing, tell the user and offer the `bm25` provider instead of stopping. It makes no API call and has no budget: windows are chosen by BM25 on the keyword string and each paper is scored by BM25 on its abstract plus 3 windows. Output is `<prefix>_bm25.csv`. Say in the report that BM25 matches words, not meaning, so synonyms are missed and the order is rougher; never compare its scores with a voyage run.

`--variants hybrid,dense` adds a dense-only ablation (voyage only). `--ids <csv>` ranks exactly the listed paper ids, for comparing runs on a frozen corpus.

## What to tell the user

- A rank is a lead, not evidence. Similarity is not quality. A claim needs someone to read the page.
- `_pages` shows where the reranker looked; the key passage can still sit elsewhere in the paper.
- Publisher sites often refuse downloads (HTTP 403). List the `MANUAL` lines for the user. Never work around paywalls, logins or bot checks.
- A preprint is not the published version; say which one was downloaded.

## Examples

**New project.** User: "Rank my PDFs for energy-efficient routing in underwater acoustic sensor networks." No `literature.json`: ask where the PDFs are, write it. Offer candidate questions (for example "Which routing protocol minimises energy per delivered packet in an underwater acoustic sensor network?") and take the user's pick or their own wording. Ask the slot screens (`subject` suggestion: "Underwater acoustic sensor network nodes on battery"; `comparison`: "Depth-based routing" or "Leave empty"), write the queries from the answers, show the table, apply the user's edits, freeze `queries.json`. Dry run, report the estimate, run, report the fused top 10 with starting pages.

**Rerun after new PDFs.** User: "Add the 12 PDFs from yesterday and rerank with the frozen queries." Use the existing config and queries file, rank the whole collection, compare with the previous `_run.json` and report papers that entered or left the fused top 10.

**Search and fetch only.** User: "Find papers citing Bhambay 2025 and download the open ones." `openalex_search.py --cites <doi>` (OpenAlex holds few links for very recent preprints; Semantic Scholar's citations endpoint is the fallback), then `fetch_pdf.py --from <file>.jsonl`. Report counts, how many were already in `sources`, and the `MANUAL` list.
