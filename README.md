# paper-lector

Ranks research PDFs and suggests starting pages; reading leads, not evidence.

paper-lector is a Claude Code skill with three scripts:

- `openalex_search.py` searches OpenAlex (semantic, exact boolean, citing works, references).
- `fetch_pdf.py` downloads open-access PDFs (arXiv first, then OpenAlex locations) and lists the rest for manual download.
- `rank.py` ranks your own PDF collection against a few frozen research-question queries. It splits each PDF into page-labelled windows, picks the best windows per paper with BM25 plus `voyage-4-large` embeddings, scores each paper with `rerank-3`, and fuses the per-query ranks into a reading order.

`SKILL.md` is the full guide that Claude reads.

## Install

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector
```

`pdftotext` (poppler) must be on `PATH`. Put `OPENALEX_API_KEY` and `VOYAGE_API_KEY` in the environment, the project `.env`, or `~/.config/paper-lector/.env`.

## Use in a project

Add `literature.json` at the project root:

```json
{"pdf_dirs": ["pdfs"], "download_dir": "pdfs/new", "queries": "queries.json"}
```

See `examples/` for a config and a queries file. Then ask Claude, for example: "Rank my PDFs for this question: ...".

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

The tests run offline: small generated PDFs, a word tokenizer and a fake Voyage API.
