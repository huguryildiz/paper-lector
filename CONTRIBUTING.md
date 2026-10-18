# Reporting a problem

Open an issue at https://github.com/huguryildiz/paper-lector/issues with:

1. The paper-lector version and commit: `paper_lector_version` and `paper_lector_commit` in the run's `_rank_run.json`, or `git -C <paper-lector folder> describe --always --dirty`.
2. Your system and `pdftotext -v` (the first line).
3. The exact command and the full message it printed.
4. For a ranking problem, the `_rank_run.json` and the dry-run lines of the papers concerned. A PDF only if you may share it.

Never paste an API key, a `.env` file or a key-bearing URL into an issue. Security problems go by [`SECURITY.md`](SECURITY.md), not an issue.

## Changing the code

A behaviour change touches the code, its tests, `SKILL.md` and `REFERENCE.md` together. Run the tests before a pull request:

```bash
.venv/bin/pip install -r requirements.txt -c constraints.txt pytest==9.1.1
.venv/bin/python scripts/rank.py --setup --provider local    # once; lets the real-model tests run
.venv/bin/python -m pytest -q
```
