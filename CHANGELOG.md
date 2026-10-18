# Changelog

Versions follow `common.VERSION`; version 0.1.0 is git tag `v0.1.0`. Every `_rank_run.json` records the version and the commit (`-dirty` when a tracked file of the checkout differed from it).

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
