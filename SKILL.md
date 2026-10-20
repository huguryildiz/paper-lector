---
name: paper-lector
description: Search OpenAlex, download open-access PDFs, and rank a researcher's own PDF collection against frozen research-question queries, giving a reading order with the pages to start on. Use for a literature search, a citation chase, fetching papers' PDFs, or "which of my PDFs should I read first for this question". It gives reading leads, not evidence, and does not answer questions or write reviews.
---

# paper-lector

Ranks a PDF corpus against fixed research questions to prioritize reading, indicating where each paper should be read first, without establishing what it reports.

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python        # the skill's venv (native arm64 on Apple Silicon); pdftotext must be on PATH
```

The commands below assume macOS or Linux with a Unix shell; on Windows they need WSL.

On a new machine, run `$PY $PL/scripts/rank.py --setup` once while online. It checks for `pdftotext` (printing the install command if missing) and downloads the tokenizer that every rank run needs, also `--dry` and `local`. With `--provider local` it also downloads the local model (130 MB, once; `--local-model retrieval` for the other one); after that, the `local` provider works offline.

| Step | Command | Output |
| --- | --- | --- |
| Search | `$PY $PL/scripts/openalex_search.py --exact '<query>' --name <name>` | `runs/<date>_<time>_<name>_<mode>_search.jsonl` next to the config, one JSON line per work: abstract, open-access PDF link, `in_sources`. `--exact` is unstemmed: `schedul*` matches scheduling and schedules. Writes the query record beside it, the same name with `.query.json` in place of `.jsonl` |
| Overlap | `$PY $PL/scripts/search_overlap.py <file>_search.jsonl <file>_search.jsonl` | works per file, shared, distinct; with keyword and semantic files, the share of semantic works keyword also found (`LOW OVERLAP` under half) and the titles found only by semantic |
| Fetch | `$PY $PL/scripts/fetch_pdf.py --from <file>.jsonl` or `... fetch_pdf.py <doi> <arxiv id> <W id>` | PDFs in `download_dir` and `fetch_log.jsonl` (status `OK` with source URL and SHA-256, `HAVE` for a download identical to a PDF already held, or `MANUAL` with title and landing URL); `MANUAL` lines for the rest, `ERROR` for failed lookups or when no URL could be reached; exit 1 if any paper is missing |
| Rank | `$PY $PL/scripts/rank.py --dry`, then without `--dry` | `runs/<date>_<time>_<name>_rank.csv` and `_rank_run.json` next to the config, and one line in the project's `questions.jsonl` |

Write outputs outside the project's tracked files (a scratch or `runs/` folder) unless the user asks to keep them.

## Step 1: the project config

Every script except `search_overlap.py` looks for `literature.json`, starting in the current folder and walking up to the project root (the first folder with `.git`). Paths in it are relative to its own folder.

```json
{
  "pdf_dirs": ["pdfs"],
  "download_dir": "pdfs/new",
  "sources": "sources.csv",
  "queries": "queries/entanglement-scheduling.json",
  "rank": {"provider": "voyage"}
}
```

- `pdf_dirs` (required): folders searched recursively for PDFs.
- `download_dir`: where `fetch_pdf.py` saves; defaults to the first `pdf_dirs` entry. `rank.py` ranks it too when it lies outside `pdf_dirs`.
- `sources` (optional): a CSV with `key`, `pdf_path` and `doi` columns. Papers listed there keep their key as id; other PDFs are named by file stem, with `-2`, `-3` added when two files share a name. If the file is missing, the scripts note it and continue without it.
- `queries`: the frozen queries file for `rank.py`. Keep queries files in a `queries/` folder named after their `name` (`queries/entanglement-scheduling.json`; a revision of the same question is `queries/entanglement-scheduling-v2.json` with the same `name`). The project keeps one `questions.jsonl`, beside the config's queries file (else in `queries/`), so every queries file is checked against the same history wherever it lies.
- `rank` (optional): `{"provider": "voyage"}` (default) or `{"provider": "local"}`. `--provider` overrides it for one run.

A project then looks like this: `literature.json`, `sources.csv`, `queries/` (queries files and `questions.jsonl`), `pdfs/` (PDFs and `fetch_log.jsonl`) and `runs/` (every search and rank output, named by date, time, name and kind).

If there is no `literature.json`, ask the user once where their PDFs are, then write the file. Do not guess.

Before Step 2, count the PDFs once each: `find <each pdf_dirs folder> <download_dir> -iname '*.pdf' | sort -u | wc -l` (give `download_dir` only when it lies outside `pdf_dirs`; `rank.py` ranks it too), plus the rows of `sources` whose file exists and lies outside those folders (a file inside them is already counted). If a folder is missing or the count is 0, stop and ask with AskUserQuestion: "Search OpenAlex and download open-access PDFs" (recommended; "Searching OpenAlex" below, then Fetch, then come back here), "Point to another PDF folder" (update `pdf_dirs`), or "Stop". Do not start the question screens for an empty collection.

**Progress list.** If the host has a task-list tool (the plan list or TodoWrite in Claude Code, `update_plan` in Codex), show the run as a list before the first step and tick each step off as it finishes. Also write the same numbered list once in chat before the first step, because some hosts (the Claude desktop app) show the task list in a side pane the user may not have open; do not repeat it in chat later. One emoji per step, step names in the user's language:

1. ⚙️ Check config and PDF folders
2. 🔎 Choose search modes and approve the queries
3. 🌐 Search OpenAlex
4. 📥 Download PDFs
5. ✍️ Fill the query slots
6. 🧮 Dry run and token estimate
7. 🏆 Rank and report

Drop steps 2–4 when the collection already has PDFs, and stop after step 4 for a search-only request. Add a step for anything extra the user asked for (for example ✂️ screening abstracts before the download).

Keys: `OPENALEX_API_KEY` (search, fetch; optional but recommended) and `VOYAGE_API_KEY` (rank, voyage provider only) are read from the environment, then the project `.env`, then `~/.config/paper-lector/.env`. Never put a key on a command line, in chat or in any other file.

Check the keys in step ⚙️, before any search or question screen. This prints only `found` or `missing`, never a value:

```bash
$PY -c "
import sys; sys.path.insert(0, '$PL/scripts'); import common as c
cfg = c.load_config(required=False)
for n in ('OPENALEX_API_KEY', 'VOYAGE_API_KEY'):
    try: c.api_key(n, cfg); print(n, 'found')
    except SystemExit: print(n, 'missing')
"
```

Check only the keys the run needs: OpenAlex for search and fetch, Voyage for ranking with the voyage provider. For each missing one, ask with the question tool and never collect the key through it: whatever the user types in its free-text field lands in the chat. Show the user this command for their own terminal (the Terminal panel or Terminal.app; a `!` shell in Claude Code cannot read input), with `<NAME>` filled in. `read -s` hides the typing, so the key goes straight to the file:

```bash
mkdir -p ~/.config/paper-lector && touch ~/.config/paper-lector/.env && chmod 600 ~/.config/paper-lector/.env && read -rs "k?<NAME>: " && echo "<NAME>=$k" >> ~/.config/paper-lector/.env && unset k
```

In bash the `read` part is `read -rsp "<NAME>: " k`. The `chmod 600` keeps the file readable by the user only; a script that finds a key in a file other users can read prints a note with the same `chmod`. Options: "I added it, continue" (recommended; run the check again, and ask again if it is still missing), "Use the local model instead" (Voyage only; say in its description that it downloads 130 MB once and suits English PDFs; see "No Voyage key" below), "Continue without a key" (OpenAlex only), "Stop". If a search or a fetch stops with `OPENALEX_API_KEY is wrong`, or `rank.py` with `Voyage refused the key`, the key is there but wrong or revoked: say so and show the same screen.

OpenAlex without a key: fetch works. Keyword and citing searches return only the first page, at most 200 works; references come back whole (one request per 100); semantic stops at 50 with or without a key. The daily budget is about 100 searches, shared by everyone on the same IP address. The free key (openalex.org, a few minutes) removes the page limit and gives ten times the budget. Say this in the "Continue without a key" description. When a keyless search prints `only the first N of M were written`, report both numbers. When a script stops with `daily budget is used up`, report the reset time and show the key screen.

## Searching OpenAlex

`openalex_search.py` has four modes. Before any search, ask which ones with the question tool, multi-select (`multiSelect: true` in Claude Code; where the tool has no multi-select, add a "Keyword + semantic" option to the single choice and mark it recommended; the user can also type several modes in the free-text field, such as `keyword, citing` or `all`, and every mode named there is run), unless the user's request already names it ("papers citing X" is citing, "X's references" is references). Recommend keyword and semantic together: semantic finds the papers written in other words, and the overlap shows what the keyword query missed (on the entanglement-scheduling example, 20 of 50 semantic works were in the keyword results):

| Option | Flag | Tell the user |
| --- | --- | --- |
| Keyword (recommended) | `--exact '<boolean query>'` | Words in the title and abstract, with AND / OR / NOT and `*` wildcards. Every match, and the same list again on the same OpenAlex data. Misses papers that use other words |
| Semantic (recommended) | `--semantic '<sentence>'` | Matches by meaning, so it finds papers in other words. At most 50 results, and the list can change between runs |
| Citing works | `--cites <DOI, arXiv id or W id>` | Papers that cite one paper; forward in time |
| References | `--refs <DOI, arXiv id or W id>` | Papers one paper cites; back in time |

Then write one search per chosen mode from the user's topic: a keyword query (rules below), one plain sentence for semantic, or the seed paper's DOI for citing and references (ask for the seed if the user has not named one). Above them, propose the topic `name` (rules in Step 2; reuse one from `questions.jsonl` if the same question was asked before). Show them all together and ask, on a single-choice screen, "Run this search" (recommended), "Edit it" (the user types the new text in the free-text field), or "Change the mode". Run only after the user approves; never run a query the user has not seen. After an edit, if you change anything in the user's text (a bracket, a `*`, a term), show the new text on the same screen again; run the user's own text unchanged only when it passes the check below as typed.

A keyword query has two blocks:

    (setting terms, joined by OR) AND (task terms, joined by OR)

- `setting`: the field, system, population or material the question is about.
- `task`: the problem, intervention or kind of method it looks for there.

- At most 6 terms in total, at least 1 per block (2 + 4, 3 + 3). Fewer is fine; never add a term to fill a place.
- The task block holds at least one topic term: the problem, the object designed, the process studied, in words any relevant paper would use. Method or algorithm names come only beside one. Check: would a relevant paper that names none of the method terms still be found?
- Leave out metrics and outcomes (delay, accuracy, energy), which are read from the papers found; words most papers of any field hold (model, method, approach, system, optimization alone); and a term with a general word welded on ("X optimization" when authors write "X").
- Use the words authors of that field write in titles and abstracts, with common synonyms and abbreviations in the same block.
- The search is unstemmed: "routing" does not match "routes". Put `*` on a stem that begins only the words you mean (`schedul*`, `entangl*`); `rout*` also matches routine and gives millions. Otherwise list the forms (`routing OR routes`). No `*` or `?` inside quotes once the query has more than one term: OpenAlex refuses `"quantum network*"` in a boolean query (alone it works); write `"quantum network" OR "quantum networks"`.
- Quote a multiword term. Give each block its own parentheses and join the blocks with AND.

`openalex_search.py` refuses a query OpenAlex would misread and sends nothing: an empty query or group, an operator with no term on one side, NOT NOT, lower-case and/or/not (searched as words: write operators in capitals), OR at one level with AND, NOT or plain adjacency (`"quantum switch" scheduling OR "operations research"` returns the works of the phrase alone), empty quotes, unbalanced quotes or brackets, brackets nested more than 10 deep, `*` or `?` inside quotes when the query has more than one term, and more than 5 AND/OR/NOT. Fix the query, then show it again.

Run each approved search with `--name <name>` and without `--out`: the script names the file by date, time, name and mode under `runs/`, for example `runs/2026-10-18_1420_entanglement-scheduling_exact_search.jsonl` (`-2` after the time when that minute is taken). It writes the mode, the query text, the date and the counts to a record next to it, the same name with `.query.json` in place of `.jsonl` (`runs/x_search.jsonl` gives `runs/x_search.query.json`), so the run can be traced and repeated. Report the `count` and `written` numbers per mode and how many were already in `sources`. For semantic, say that only the 50 closest works came back. With more than one mode, run `$PY $PL/scripts/search_overlap.py <file> <file> ...` and report how many works the files share (same DOI, arXiv id or OpenAlex id) and the number of distinct works; fetch from each file in turn, since `fetch_pdf.py` never saves the same PDF twice.

When it prints `LOW OVERLAP` (under half of the semantic works are in the keyword results), the keyword query probably misses words the field uses. Read the `only semantic` titles and abstracts, name the words the relevant ones share that the query lacks (a synonym, a narrower task, the abbreviation's plural), and write one revised keyword query under the same rules. Show it with the words it adds on the approval screen: "Run the revised search" (recommended), "Edit it", or "Keep the first". The revised search goes to a new file and the first stays; fetch from the revised file and the semantic one. Revise once; if the overlap stays low, report it and move on. Say that semantic stops at 50, so the overlap is a check, not a count of what was missed.

After every fetch, report in this order, from the last line `fetch_pdf.py` prints (`ok N  have N  manual N  error N  skip N`), adding up the lines when several files were fetched:

1. One sentence with all five numbers out of the works tried, in the user's language: "Of 35 works, 18 PDFs were downloaded, 2 were already in the collection, 15 are on publisher sites, 0 lookups failed, 0 records had no id." Name the folder the new PDFs went to.
2. The `MANUAL` table (rules under "What to tell the user" below), or "none".
3. Each `ERROR` and `SKIP` line with its reason, or nothing when there are none.

Then the PDF count for ranking: the PDFs now in `pdf_dirs`. When `manual` is not 0, the "Missing PDFs" screen comes next.

## Step 2: writing the queries

Fill all six slots and the fuse choice on question screens before writing any query text. Use the host's multiple-choice question tool: `AskUserQuestion` in Claude Code, `request_user_input` (or `request_user_input_async`) in Codex, the equivalent in other agents.

The answers are required in every host. Keep the questions open until the user answers; never fill a slot by assumption, after a timeout, or because the tool returned no answer. If the tool returns nothing, ask the same questions in chat.

Six labels, all optional except `main`:

| Label | Asks | Example (which user gets an ageing entangled pair) |
| --- | --- | --- |
| `main` | The whole question in one neutral sentence; no hoped-for result | Which competing request should receive an ageing stored entangled pair? |
| `subject` | What is studied: system, population, phenomenon, material, model | Quantum switch with memories and waiting requests |
| `approach` | What is done: method, intervention, design, algorithm, procedure | Service discipline, scheduling policy |
| `outcome` | What is measured or concluded: metric, effect, performance, property | Age of entanglement, fidelity, cost |
| `context` | Where or under which conditions | Underwater links, delayed control |
| `comparison` | Alternatives or baselines | First-come-first-served, random choice |

Ask seven questions in this order: `main`, `subject`, `approach`, `outcome`, `context`, `comparison`, `fuse`. Put as many on one screen as the tool allows:

- 4 per screen (`AskUserQuestion`): `main`, `subject`, `approach`, `outcome`; then `context`, `comparison`, `fuse`.
- 3 per screen (Codex's tool may take only 3): `main`, `subject`, `approach`; then `outcome`, `context`, `comparison`; then `fuse`.
- Fewer: keep the order and use more screens.

The `fuse` question is single choice, so it works without multi-select: "main + subject" (recommended), "main + subject + approach + outcome", "main only", or the user's own list of labels in the free-text field. Slots left empty are dropped from the chosen set. Ask it in plain words, without "fuse" or `fused_rank`, for example "Which questions should set the final reading order?" with header "Order by", and say in each description what the user gets: "your question and the system it studies; the other questions still get their own columns in the CSV", "method and metric words also count in the order", "only your question". Keep "main + subject" as the recommendation also when the question points at one specific paper: on LitSearch questions with voyage, main only did better with one set of blind `subject` sentences (MRR +0.12 on 46) and the same with another (−0.01 on 48), so the effect depends on how `subject` is written (`examples/litsearch/MINI-TEST.md`).

Each slot question names the slot and what it asks, for example "approach: what is done (method, intervention, design, algorithm)?", with header = the label. On the screens, write the slot names, headers and option labels in the user's language (in Turkish: ana soru, konu, yöntem, ölçüt, koşullar, karşılaştırma; "Boş bırak" for "Leave empty"). The English labels stay in `queries.json`, the query table and the CSV columns; when you first show the table, give each label next to its name in the user's language. It offers three ways to fill the slot:

- Claude's suggestion: one short phrase drawn from the user's request and what the project already holds (the topic they named, the titles in `sources` or the PDF folders, an existing `queries.json`), written like the example column, marked recommended, the description saying why it fits.
- The user's own wording, typed in the tool's free-text field ("Other" in `AskUserQuestion`) and used as given.
- "Leave empty".

`main` cannot be left empty; say so in its question ("main (required): ..."), so the user does not try the tool's Skip button. Its two options are candidate questions, each one neutral sentence; if the user's request already states the question, that sentence word for word is the first option. The chosen or written question becomes the `question` field and the `main` slot; if the user edits a candidate, the edited text wins.

Without such a tool, ask the same questions in chat, one numbered list per slot, and wait for the reply.

From the answers, write each slot's `text` and `keywords` by the rules below, show the finished set as one table, and freeze the file only after the user approves it. Above the table, propose a `name` for the file: two or three words of the question, lowercase with hyphens, at most 25 characters (`entanglement-scheduling`). If the searches already used a name for this topic, use the same one. First read the project's `questions.jsonl` (beside the config's queries file): if the same question was ranked before, reuse its name (`rank.py` refuses another one). The name goes into the file as `"name"` and names every output of its runs; a file without one gives `paper-lector`. Never change a frozen file after seeing results; a revision is a new file and a new run. `rank.py` backs this up: it never overwrites an existing `<prefix>_<name>_rank_run.json`, and if that run was made with a different question, queries or fuse list it says so. Use a new queries file and a new `--out`.

Rules for drafting:

- Each `text` is one English sentence of about 20 to 50 words; each `keywords` is a short BM25 string of the same meaning.
- If some PDFs are not in English (for example Turkish theses or journal papers), add that language's terms to `keywords` next to the English ones (`energy routing enerji yönlendirme`). BM25 matches words, so English keywords alone miss those papers; `voyage-4-large` embeddings and `rerank-3` are multilingual and handle `text` as it is. The local models are English only: for papers in other languages use the voyage provider. `rank.py` finds abstract, introduction, bibliography and appendix headings in English, Turkish, German, French, Spanish, Italian, Portuguese and Russian. In other languages it falls back to the first 1,000 tokens, and a bibliography stays unless it is a numbered list of dated entries, which is cut in any language; the dry run shows this as `-` in the `abs` and `bib` columns. Chinese, Japanese and Korean text has no spaces between words, so BM25 does not work on it; use the voyage provider for those papers.
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

If the user names papers they expect near the top, write their ids down before the run and pass them as `--expect id1,id2`. When you ask for them, offer only "none" and the free-text field for the user's own papers; never suggest papers yourself, since a check built from your picks tests nothing. `rank.py` checks them against the top 10 of the first query in the file (the lowest id with text, usually `Q0`, the `main` one) only, not against the fused order or any other query. An id that names no paper is reported as missing, so copy ids from the dry run. They are a sanity check, not a test, once their ranks have been seen.

## Step 3: ranking

**Missing PDFs.** After a fetch with `MANUAL` papers, show their table and ask with the question tool before ranking: "I'll add the PDFs" (the user downloads them into `download_dir`, or names another folder to add to `pdf_dirs`; wait, count the PDFs again, then rank), "Continue without them" (recommended when the user has no access) or "Stop". Either way, when the papers came from a search, pass every search JSONL of this run to `rank.py --abstracts <file>[,<file>]`: each paper, with or without a PDF, also gets an abstract-only rank (`abs_fused_rank`), and papers with no PDF appear as `source` `abstract_only`. Abstract-only scores run lower than full-text ones, so `fused_rank` (full text, with pages) and `abs_fused_rank` (abstracts, all papers) are two separate orders; never merge them into one list.

1. Run `rank.py --dry` (add `--abstracts` as above). Do not pass `--out`: outputs are named by date and time under `runs/`, for example `runs/2026-10-17_2315_entanglement-scheduling_rank.csv`, and each run without `--dry` adds a line (time, question, queries file, its hash, output) to the project's `questions.jsonl`, its list of questions asked; a dry run writes nothing. It prints counts per paper (tokens, windows, bibliography cut, abstract found) and, for the voyage provider, the token estimate, with no API call. Report the estimate (a local dry run has none: say it costs nothing).
2. Run without `--dry`. It stops before any API call if the estimate is above `--budget` (15M tokens by default; about 350 PDFs with their abstracts). When it stops there, show the user the estimate and what it would cost (prices below), and ask with the question tool: "Raise the budget to <estimate rounded up>" (recommended when the cost is acceptable; rerun with `--budget N`), "Rank with the local model instead" (no cost) or "Stop". Never raise `--budget` without that answer. During the run every request to Voyage, retries included, counts against `--budget`, and the run stops before a request that would pass it. Embeddings are cached in `~/.cache/paper-lector/embeddings.sqlite`, so a rerun or a run restarted after a crash does not pay for them again. Reranking is not cached: it is paid in full on every run, about half the tokens of a first run (the estimate counts everything). The cache is shared by every project on the machine; its `src` table ties each vector to the PDF's SHA-256, window number and pages, or to the queries hash and query id. Voyage gives 200M free tokens per model; after that `voyage-4-large` costs $0.12 and `rerank-3` $0.05 per million tokens.
3. Report the fused top 10, where it disagrees with single queries, and with `--abstracts` also the top 10 by `abs_fused_rank`, marking each paper with no PDF (a paper to get: with its PDF it would be ranked on full text too) and naming any `abstract_only` paper with no abstract (unranked), and the sanity check result as it is. Name every paper skipped for having no text or a failed extraction (dry-run `skipped` lines, `corpus.skipped` in `_rank_run.json` with the reason); they are missing from the order. Name every `possible duplicate` pair (dry-run lines, `corpus.possible_duplicates`): both copies were ranked, so one paper takes two places. Ask which copy to keep and let the user move the other out of `pdf_dirs`; never delete a PDF yourself. Byte-identical copies are already skipped with a note.

What happens inside: the whole PDF is split into 1,200-token windows with page labels (every bibliography cut, from a References heading or, with none, from a numbered list of dated, authored entries, up to where the entries stop; appendices, supplementary material and chapters after a chapter's bibliography kept). For each paper and query, the 3 best windows are chosen by fusing embedding similarity (`voyage-4-large`) with BM25 on the keyword string. The reranker (`rerank-3`) then scores each paper once per query on its abstract plus those 3 windows; the windows leave out the abstract's text, so it is not read twice (in a PDF shorter than about 1,000 tokens with no abstract heading, the one window is that same opening, and it is read twice). Adding PDFs changes BM25 statistics, so rerun the whole collection rather than ranking only the new files.

Output columns, reading columns first: `fused_rank`, `abs_fused_rank` (with `--abstracts`), `citation` (authors, year, title, venue, volume, pages; from the search record, so filled with `--abstracts`), `link` (DOI, else arXiv or OpenAlex page), `cited_by`, `cited_pct`, `start_pages` (up to three page ranges where the `fuse` queries' windows agree, most votes first, overlapping ranges skipped; empty without a PDF), then `paper`, `fused_score`, `cited_at`, per query `<id>_<label>_rank` and `_score`, then per query `<id>_<label>_pages` (the pages the reranker read, a place to start reading), then `tokens`, `bib_cut`, `abstract_found`, `source` (`full_text` or `abstract_only`), and with `--abstracts` `abs_fused_score`, per query `<id>_<label>_abs_rank` and `_abs_score`, and `abstract_from` (`search`, `pdf` or empty). `<prefix>_<name>_rank_run.json` records the question, queries, fuse list, models, parameters, corpus ids with each PDF's SHA-256, the SHA-256 of the queries file, config, sources table and fetch logs, token usage, the command, the working folder, the operating system, and the paper-lector version and commit (`-dirty` when any tracked file of the paper-lector checkout was changed after it).

**No Voyage key.** If `VOYAGE_API_KEY` is missing, the key screen in step ⚙️ offers the `local` provider instead of stopping. It makes no API call and has no budget. It uses `potion-science-32M`, an English model2vec model of static token vectors (MIT licence), kept in `~/.cache/paper-lector/`; if it is not there yet, run `$PY $PL/scripts/rank.py --setup --provider local` first and tell the user it downloads 130 MB once. `"rank": {"provider": "local", "model": "retrieval"}` (or `--local-model retrieval`) uses `potion-retrieval-32M` instead (131 MB); keep the default unless the user asks. If most PDFs are not in English, tell the user the local order will be poor and suggest a Voyage key. Windows are chosen by fusing its cosine similarity with BM25 on the keyword string, and each paper is scored by the cosine between the query `text` and its abstract plus 3 windows; there is no reranker. Output is `<prefix>_<name>_rank-local.csv`. Say in the report that the order is rougher than a voyage run: on [`examples/entanglement-scheduling`](examples/entanglement-scheduling), 73 PDFs, its fused order agreed with the voyage run at Spearman 0.79 and its abstract order (139 papers) at 0.78, and the two top 10s shared 5 papers (README, step 5). Never compare its scores with a voyage run. A config that still says `"provider": "bm25"` stops and asks for `local`.

`--variants hybrid,dense` adds a dense-only ablation (voyage only). `--ids <csv>` ranks exactly the listed paper ids, for comparing runs on a frozen corpus; give it a `sha256` column from `corpus.files` in the earlier `_rank_run.json` so a different file under the same id stops the run. On a large collection `rank.py` and `fetch_pdf.py` can run for several minutes (about 2 to 3 minutes for 500 PDFs with the local provider, longer with Voyage; a fetch of many papers longer still). Run them in the background or with a long timeout, so the agent's tool does not kill them half-way; a killed rank run leaves its lock behind.

When a script stops on an error (no network, a full disk, a refused key, Voyage's rate limit, an invalid API answer, a broken line in a search or log file), it says what to do and keeps no partial output: report its message to the user as it is, fix the cause with them, and run the same command again. If a run stops with `<prefix>_<name>_rank_run.lock exists`, check that no other rank run is going before you delete the lock; never delete a lock or partial output of a run that may still be running.

## What to tell the user

- A rank is a lead, not evidence. Similarity is not quality. A claim needs someone to read the page.
- `_pages` and `start_pages` show where the reranker looked; the key passage can still sit elsewhere in the paper.
- Publisher sites often refuse downloads (HTTP 403). Show every `MANUAL` paper in a table, never only the count: title and year (from the search JSONL), the DOI as a `https://doi.org/...` link (or the arXiv or W id when there is no DOI) and the landing URL from the `MANUAL` line. Never work around paywalls, logins or bot checks.
- A preprint is not the published version; say which one was downloaded.

## Examples

**New project.** User: "Rank my PDFs for energy-efficient routing in underwater acoustic sensor networks." No `literature.json`: ask where the PDFs are, write it. Ask the question screens: `main` candidates (for example "Which routing protocol minimises energy per delivered packet in an underwater acoustic sensor network?"), a suggestion for each other slot (`subject`: "Underwater acoustic sensor network nodes on battery"; `comparison`: "Depth-based routing"), each with "Leave empty" except `main`, and the user's own wording through "Other". Write the queries from the answers, show the table, apply the user's edits, freeze `queries/underwater-routing.json`. Dry run, report the estimate, run, report the fused top 10 with starting pages.

**Rerun after new PDFs.** User: "Add the 12 PDFs from yesterday and rerank with the frozen queries." Use the existing config and queries file, rank the whole collection (a new dated output), compare with the previous `_rank_run.json` and report papers that entered or left the fused top 10.

**Search and fetch only.** User: "Find papers citing Bhambay 2025 and download the open ones." The request names the mode, so skip the mode question; show the seed DOI for approval, then `openalex_search.py --cites <doi>` (OpenAlex holds few links for very recent preprints; Semantic Scholar's citations endpoint is the fallback), then `fetch_pdf.py --from <file>.jsonl`. Report counts, how many were already in `sources`, and the `MANUAL` list.
