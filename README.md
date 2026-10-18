<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img src="assets/icon.svg" alt="paper-lector logo" width="120" height="120">
</p>

<h1 align="center">paper-lector</h1>

<p align="center">
  <strong>Agent Skill for Claude Code and Codex</strong><br>
  <sub>Ranks a PDF corpus against fixed research questions to prioritize reading, indicating where each paper should be read first, without establishing what it reports.</sub>
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
  <a href="#example-quantum-network-scheduling">Example</a>
  &nbsp;·&nbsp;
  <a href="#search-modes">Search modes</a>
  &nbsp;·&nbsp;
  <a href="#how-ranking-works">How it works</a>
  &nbsp;·&nbsp;
  <a href="REFERENCE.md">Reference</a>
</h3>

---

## Overview

paper-lector is an agent skill for Claude Code and Codex with three scripts:

- `openalex_search.py` searches OpenAlex (keyword, semantic, citing works, references).
- `fetch_pdf.py` downloads open-access PDFs and lists the rest for manual download.
- `rank.py` ranks your own PDFs against a few frozen research-question queries and tells you which pages to read first.

[`SKILL.md`](SKILL.md) is the guide the agent reads. [`REFERENCE.md`](REFERENCE.md) has every option, output file and edge case.

## Install

paper-lector runs on macOS and Linux, and CI tests both. Windows is not supported: the commands below and in [`SKILL.md`](SKILL.md) assume a Unix shell, so on Windows use WSL. You need Python 3.12 and `pdftotext` from poppler: `brew install python@3.12 poppler` on macOS; `sudo apt install python3.12 python3.12-venv poppler-utils` on Ubuntu 24.04. Where the system has no Python 3.12 package (Debian 13 ships 3.13, Ubuntu 22.04 3.10), install 3.12 with pyenv or the deadsnakes PPA.

```bash
git clone https://github.com/huguryildiz/paper-lector ~/Documents/GitHub/paper-lector
cd ~/Documents/GitHub/paper-lector
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -c constraints.txt
mkdir -p ~/.claude/skills ~/.codex/skills
ln -s ~/Documents/GitHub/paper-lector ~/.claude/skills/paper-lector   # Claude Code
ln -s ~/Documents/GitHub/paper-lector ~/.codex/skills/paper-lector    # Codex
```

The symlink is what lets the agent find the skill; make the one for the agent you use, or both.

`constraints.txt` pins every package that `requirements.txt` pulls in, so a new install gets the versions the tests ran with.

Add your API keys to `~/.config/paper-lector/.env` (shared by all projects) or to a project's `.env`:

- `OPENALEX_API_KEY` for search and fetch. It is optional but recommended. The key is free: sign up at [openalex.org/signup](https://openalex.org/signup), then copy it from [openalex.org/settings/api-key](https://openalex.org/settings/api-key).
- `VOYAGE_API_KEY` for ranking with the default provider. Create one at [dashboard.voyageai.com](https://dashboard.voyageai.com/organization/api-keys). Voyage gives free tokens, but an account with no payment method gets low rate limits, and a run on a few dozen PDFs may stop on HTTP 429; adding a payment method in the dashboard lifts them and the free tokens still apply. Without a key, rank with `--provider local`.

```bash
mkdir -p ~/.config/paper-lector
install -m 600 .env.example ~/.config/paper-lector/.env    # readable by you only; then fill in the keys
```

Then, once and while online, check `pdftotext` and download the pinned tokenizer:

```bash
.venv/bin/python scripts/rank.py --setup
```

Without a Voyage key, add `--provider local` to that command; it also downloads the local model, [`potion-multilingual-128M`](https://huggingface.co/minishlab/potion-multilingual-128M) (531 MB).

## Example: quantum network scheduling

[`examples/entanglement-scheduling`](examples/entanglement-scheduling) is a complete run made with these scripts. The question:

> Which methods (optimization, heuristics, reinforcement learning) have been used to schedule entanglement distribution in a multi-user quantum network, and with which metrics were they compared?

**1. Config.** `literature.json` sits at the project root, and its paths are relative to it.

```json
{
  "pdf_dirs": ["pdfs"],
  "download_dir": "pdfs",
  "queries": "queries/queries.json",
  "rank": {"provider": "voyage"}
}
```

**2. Queries.** [`queries/queries.json`](examples/entanglement-scheduling/queries/queries.json) holds the question and five labelled queries (`main`, `subject`, `approach`, `outcome`, `comparison`), each written as a full sentence with a keyword string; the first four are fused. Once a queries file has produced results, it stays as it is; a changed question gets a new file.

**3a. With an agent.** Open the project in Claude Code or Codex and ask:

> Find and rank papers on how entanglement distribution is scheduled among many users of a quantum network.

The agent asks which search modes to run and shows its queries for approval. It then downloads the open-access PDFs and fills the query slots through a few questions. After a dry run it ranks the papers and reports the top 10 with the pages to start on.

**3b. From the shell.** Run this in a new, empty project folder. It writes `literature.json` and `queries/queries.json` (the example's files), and every script then finds them from that folder.

```bash
PL=$(ls -d ~/.claude/skills/paper-lector ~/.codex/skills/paper-lector 2>/dev/null | head -1)
PY=$PL/.venv/bin/python
mkdir -p ~/research/entanglement-scheduling/queries && cd ~/research/entanglement-scheduling
git init -q                           # marks the project root; the scripts look for literature.json up to here
cp $PL/examples/entanglement-scheduling/literature.json .
cp $PL/examples/entanglement-scheduling/queries/queries.json queries/

# search OpenAlex two ways, compare, download the open-access PDFs
$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --exact '("quantum network" OR "quantum networks" OR "quantum internet") AND (entangl*) AND (schedul*)'
$PY $PL/scripts/openalex_search.py --name entanglement-scheduling \
    --semantic 'Scheduling entanglement distribution among multiple users in a quantum network with optimization, heuristics or reinforcement learning'
EX=$(ls -t runs/*_entanglement-scheduling_exact_search.jsonl | head -1)      # the files just written
SE=$(ls -t runs/*_entanglement-scheduling_semantic_search.jsonl | head -1)
$PY $PL/scripts/search_overlap.py $EX $SE
$PY $PL/scripts/fetch_pdf.py --from $EX
$PY $PL/scripts/fetch_pdf.py --from $SE

# count tokens without calling the API, then rank PDFs on full text and every paper on its abstract
$PY $PL/scripts/rank.py --abstracts $EX,$SE --dry
$PY $PL/scripts/rank.py --abstracts $EX,$SE
```

`fetch_pdf.py` exits with status 1 when some papers could not be downloaded (the `MANUAL` lines), so a script that stops on errors should not stop there. Without a Voyage key, add `--provider local` to both `rank.py` lines.

The keyword search returned 137 works and the semantic search the 50 closest. They share 20, so 167 distinct works came out, and `search_overlap.py` reported LOW OVERLAP: only 40% of the semantic works were in the keyword results. `fetch_pdf.py` downloaded 73 open-access PDFs. For each paper it could not get, it wrote a `MANUAL` line with the publisher page, where the PDF can be downloaded by hand.

Ranking scored the 73 PDFs on full text. The abstract order listed 147 papers, 74 of them with no PDF; 8 had no abstract, so 139 were ranked on their abstracts. A first run on these files sends about 3.1M tokens to Voyage: 1.55M for embeddings and 1.57M for reranking (the dry run estimated 3.19M). Embeddings are cached, so a rerun does not pay for them again, but reranking is paid in full on every run, about half of a first run. The example's own run took most embeddings from an earlier run's cache and sent 0.11M embedding tokens. `rank.py` stops before any API call if the token estimate is above `--budget` (15M by default; at the size of this example, that is about 350 PDFs), and it counts every request, retries included, against that budget.

**4. Read the output.** [`runs/2026-10-18_0317_entanglement-scheduling_rank.csv`](examples/entanglement-scheduling/runs/2026-10-18_0317_entanglement-scheduling_rank.csv) has one row per paper, PDFs first by `fused_rank`, then the papers with no PDF by `abs_fused_rank`. The first columns are for reading: the full-text rank and the abstract rank, the citation, a link, the citation count and its percentile, and `start_pages`. `start_pages` gives up to three page ranges where the fused queries' windows agree. Every other column follows. `_rank_run.json` records what is needed to repeat the run: the paper-lector version and commit, the command, the SHA-256 of every PDF and of the queries file, config, sources table and fetch logs, the models and the software versions. Runs are never overwritten. Voyage serves its models under fixed names that it may update, so a voyage rerun can differ slightly; a `local` run on the same files gives the same CSV byte for byte. Scanned PDFs with no text are skipped and listed in the dry run and `_rank_run.json`.

A high rank means the text resembles the question. It does not mean the paper is good or that it answers the question.

**5. Without a Voyage key.** The same 73 PDFs ranked with `--provider local` (model2vec, no API call, 30 seconds) gave [`runs/2026-10-18_0318_entanglement-scheduling_rank-local.csv`](examples/entanglement-scheduling/runs/2026-10-18_0318_entanglement-scheduling_rank-local.csv). Its order agrees with Voyage at Spearman 0.70 on full text and 0.71 on abstracts (139 papers), but the two top 10s share only 5 papers. Voyage's top 10 with the place each paper got from the local run:

| Voyage | Local | Paper |
| ---: | ---: | --- |
| 1 | 5 | Ni & Ho (2026), Scheduling concurrent entanglement requests in quantum networks |
| 2 | 2 | Li et al. (2021), Effective routing design for remote entanglement generation |
| 3 | 25 | Ni et al. (2025), Entanglement request scheduling using deep Q-network |
| 4 | 6 | Abreu et al. (2026), QoS-aware reinforcement learning routing |
| 5 | 19 | Gu et al. (2023), ESDI: entanglement scheduling and distribution |
| 6 | 4 | Kumar et al. (2026), Making quantum networks work: routing |
| 7 | 51 | Rode et al. (2026), Learning policies for simultaneous entanglement requests |
| 8 | 8 | Fittipaldi et al. (2023), Linear algebraic framework for dynamic scheduling |
| 9 | 18 | Fittipaldi et al. (2022), Linear algebraic framework for the quantum internet |
| 10 | 38 | Tran et al. (2026), Dynamic entanglement packet scheduling |

The local run keeps the papers that share the question's words, but loses several that answer its specific part, scheduling among many users: four scheduling papers drop from the top 10 to places 19 to 51, and Erçetin & Gedik (2026), *Fidelity-age-aware scheduling*, drops from 15 to 46. Its first place is a general survey, Gkelias et al. (2026), *Quantum networking fundamentals*, which Voyage puts 23rd. Static token vectors measure shared vocabulary; Voyage's reranker reads the query and the passage together. Use `local` to get started, and read further down its list than you would with Voyage.

## Search modes

`openalex_search.py` finds papers in OpenAlex in four ways. With an agent, ask for a search ("find papers on energy-aware routing in underwater networks") and it asks which modes to use, then shows the queries it wrote for you to approve.

| Mode | Flag | What you get | Use it when |
| --- | --- | --- | --- |
| Keyword | `--exact '<boolean query>'` | Every work whose title or abstract matches the words, with `AND`, `OR`, `NOT` and `*` wildcards (all pages need `OPENALEX_API_KEY`; without it, the first 200). One query per run; run it again for another | You want a complete search and know the field's words |
| Semantic | `--semantic '<sentence>'` | The 50 works closest in meaning to a sentence. Can change between runs | You are new to a field, or its papers use many names for one idea |
| Citing works | `--cites <id>` | Works that cite one paper (all pages need `OPENALEX_API_KEY`; without it, the first 200) | You want what came after a key paper |
| References | `--refs <id>` | Every work one paper cites | You want what a key paper built on |

`<id>` is a DOI, an arXiv id or an OpenAlex W id. Each mode writes a JSONL file that `fetch_pdf.py --from` downloads from. Keyword and semantic searches catch different papers, so run both; `search_overlap.py` then shows how many semantic works the keyword search also found. On the entanglement-scheduling example it was 20 of 50, under half, and the agent then names the words the keyword query lacks and proposes a revised query.

## How ranking works

1. `pdftotext` extracts each PDF and the bibliography is cut off.
2. The text is split into 1,200-token windows, each labelled with its pages.
3. For each query, the 3 best windows per paper are picked by `voyage-4-large` embeddings plus BM25.
4. `rerank-3` scores each paper on its abstract plus those windows.
5. The per-query ranks are combined with Reciprocal Rank Fusion into `fused_rank`.

Without a Voyage key, set `"rank": {"provider": "local"}` (or `--provider local`): no API call; ranking uses the model2vec model `potion-multilingual-128M` (a one-time 531 MB download) and gives a rougher order than Voyage. PDFs in Turkish, German, French, Spanish, Italian, Portuguese and Russian are handled too. The formula, a worked example and the language rules are in [`REFERENCE.md`](REFERENCE.md#how-ranking-works).

## Tests

```bash
.venv/bin/pip install pytest==9.1.1
.venv/bin/python -m pytest -q
```

The tests run offline and need `pdftotext` on `PATH`. Three of them use the real tokenizer and local model and are skipped until `rank.py --setup --provider local` has run; CI runs them all.

## Versions and issues

The version is in [`CHANGELOG.md`](CHANGELOG.md) and in every `_rank_run.json`. To report a problem, follow [`CONTRIBUTING.md`](CONTRIBUTING.md); security issues go by [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE)
