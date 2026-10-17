# TODO

Do these once the current changes have settled.

## Measure before changing the ranking

Use the 10-question LitSearch set in `examples/litsearch-eval` (gold papers known), the same frozen queries and one Voyage run per setting. Report hits in the top 3, 5 and 10 and the mean reciprocal rank of the gold papers.

- [ ] **Hybrid against dense.** Rank with `--variants hybrid,dense`. If dense does as well, BM25 in the window choice adds nothing: drop the `dense` variant, or make it the default, and say which in the README.
- [ ] **Windows per paper.** Rank with `N_WIN` = 2, 3 and 5 (now 3, a design choice, never measured). Keep 3 unless another value wins on the gold papers by more than the noise between questions; note the reranker tokens per setting.

## Small open items

- [ ] `fetch_pdf.py`: read an arXiv id from the landing URL (`arxiv.org`, `export.arxiv.org`, `arxiv-vanity.com`) when the OpenAlex record has none.
- [ ] `openalex_search.py` and `fetch_pdf.py`: turn HTTP 401/403 from OpenAlex into a "key missing or wrong" message instead of a traceback.
- [ ] SKILL: on the sanity-check screen the agent offers only "none" and the user's own papers, never papers it picked itself.
- [ ] Decide what happens to `examples/litsearch-eval` (199 MB, untracked).
