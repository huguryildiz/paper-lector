# Changelog

Versions follow `common.VERSION`; version 0.1.0 is git tag `v0.1.0`. Every `_rank_run.json` records the version and the commit (`-dirty` when a tracked file of the checkout differed from it).

## Unreleased

- `novelty-check`:
  - The citation trail runs in both directions (`--refs` and `--cites`) on the 3 to 5 closest papers, as a second round after screening.
  - The known set is picked from the project bibliography before any query, and every round is checked against it.
  - In a test run, the keyword and semantic queries found 20 of a project's 63 bibliography entries, and 26 with the citation trail added. The trail also turned up two partial blockers the queries had missed, one from each direction.

- `search_overlap.py` gives the overlap when the keyword file is empty (0 found, `LOW OVERLAP`) and says `overlap undefined` when there are no semantic works. It names each keyword file that holds fewer works than it matched (first page only without an API key, or `--max`), since the cut alone can lower the share.
- One authorization rule in SKILL, used by `search-rank` and `novelty-check`: a generated query, seed id or mode is shown before it runs unless the user delegated running searches in that scope; a query the user wrote runs unchanged once it passes the syntax check.
- `novelty-check`: the novelty type can be **Undetermined** when the papers read do not settle it. Frozen checks keep an evidence record with the version read, PDF hash, decisive quote and page, and retrieval date; cleanup deletes only what the run downloaded.
- `position`: positioning rows can be results (bound, guarantee, counterexample, evidence, validity range), so a new result under the same assumptions has a row to differ on.
- SKILL: "novel" also covers a different claimed result, matching the novelty-check facets.

## 0.3.0 (2026-11-03)

- The package now holds five modes behind one router: `discover`, `novelty-check`, `test`, `position` and `search-rank`. The old `SKILL.md` moved to `modes/search-rank.md`; search and fetch no longer need the ranking questions. Scripts are unchanged.
- `fetch_pdf.py` reads the arXiv id from more landing pages: `export.arxiv.org`, `arxiv.org/pdf/` and `arxiv-vanity.com/papers/`, with any query string dropped. A look-alike host such as `notarxiv.org` no longer counts.
- SKILL: when asking for papers to expect near the top, the agent offers only "none" and the user's own papers.
- README shortened, with a Benchmarks section.
- SKILL and REFERENCE no longer suggest `main` only for single-paper questions: a rebuilt 48-question LitSearch set (`examples/litsearch-eval`) found no difference.
- README: the Benchmarks section is one table on the set that can be rerun, with the expected values of a random order, and says what is not measured yet; a paragraph says how paper-lector differs from question-answering tools and hosted research assistants.
- `examples/litsearch-eval/baselines20.py`: BM25 (full text, abstract) and, with `--voyage`, rerank-3 on the abstract alone, scored like `evaluate20.py`. Not run on the real set yet.
- `fetch_pdf.py` writes the work's title, authors, year, venue and volume/pages from OpenAlex into each `OK` and `HAVE` line of `fetch_log.jsonl`. `rank.py` fills `link` and `citation` from that line when there is no search record (no `--abstracts`) and no sources DOI; older lines give the link only. A broken `fetch_log.jsonl` line now stops every run, not only one with `--abstracts`.
- `citation` lists up to six authors before "et al." (was three).
- SKILL: the top 10 is reported as a table (#, reference, start pages, link), each reference written in the field's usual citation style (IEEE, APA, Vancouver) or the user's, from the CSV only; the progress list is also written once in chat.
- MINI-TEST.md says which sections ran in the deleted working folder and cannot be rerun, and that DEIXIS's rerank misses the gold paper in 6 of its 19 questions.

## 0.2.0 (2026-10-18)

- The `local` provider uses `potion-science-32M` (130 MB, English) instead of `potion-multilingual-128M` (531 MB). `"rank": {"provider": "local", "model": "retrieval"}` or `--local-model retrieval` picks `potion-retrieval-32M` (131 MB) instead. On the 73 PDFs of `examples/entanglement-scheduling`, Spearman against the voyage run (full text, abstracts) went from 0.70 and 0.71 to 0.79 and 0.78 (science) or 0.81 and 0.75 (retrieval).
- The local models are English only. For PDFs in other languages use the voyage provider.
- The old model's folder, `~/.cache/paper-lector/potion-multilingual-128M/` (531 MB), is no longer used and can be deleted.
- `examples/entanglement-scheduling` has one local run per model (`2026-10-18_0541`, science; `2026-10-18_0542`, retrieval), replacing the multilingual run.

## 0.1.0 (2026-10-18)

First release for use outside the author's projects.

- Search OpenAlex (keyword, semantic, citing, references), fetch open-access PDFs, rank a PDF collection against frozen queries with Voyage (`voyage-4-large`, `rerank-3`) or a local model2vec model.
- Outputs are all or none: a full disk, a refused key, no network, an invalid Voyage answer or Ctrl-C while the outputs are written stops a script with a message and leaves no partial CSV, run record, search file or unlogged PDF. A run killed outright (SIGKILL, power loss) can leave its `_rank_run.lock`, which the next run names.
- A rerank answer that misses a document or holds a non-numeric score stops the run instead of ranking on it; an embedding that is missing, zero, not finite or of the wrong size is never cached, and a cached one of another size is fetched again.
- `--budget` also meters the run: every Voyage request, retries included, counts against it.
- `fetch_pdf.py` saves to drives without hard links (FAT, exFAT, some network folders), stops after 3 papers in a row reach no server, and refuses NAT64 addresses of private hosts.
- Records with the same title count as one paper only when their first authors and years agree.
- Matching 1,000 search records to PDFs takes about 10 s (was 150 s).
- A CSV cell starting with a line break is escaped like a formula.
- Logs (`questions.jsonl`, `fetch_log.jsonl`) get a whole line or none, also when the disk fills mid-write.
- API keys are not sent on redirects and are replaced by `***` in error messages that quote a server; a refused OpenAlex key also stops `fetch_pdf.py`.
- Model downloads give up after 120 s without data; a query longer than rerank-3's 8,000 tokens stops before any call.
- The run record holds the version, the command, the working folder, the operating system, the PDF paths relative to the project and the SHA-256 of the queries file, config, sources table and fetch logs.
- `constraints.txt` pins every package `requirements.txt` pulls in (pytest is pinned in CI and CONTRIBUTING); CI runs on Ubuntu and macOS, with the real tokenizer and local model and an end-to-end local run.

The run records in `examples/` were made before this version existed. They name commit `0635f0b`, although the code that made them was the working tree that became `7104a7d`; their CSVs match a rerun with `7104a7d`.
