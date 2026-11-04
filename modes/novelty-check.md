# Novelty check (kill search)

Try to destroy a claim before anyone spends months on it. A search can kill or narrow a claim. It cannot prove that a claim is new, because indexes, vocabulary and unread papers all leave gaps. The output is a scoped verdict, a novelty label, a three-axis judgement and a list of what stayed unresolved, never "this is original" or "this is the first".

## Choose the level

- **Light** (default): exploration. The claim and kill rule are written in the conversation and the approver accepts the queries. The approver is the user unless the project names someone else. No project records are written.
- **Frozen**: only when the user asks. Suggest it once when the claim is about to be stated as a contribution in a manuscript. Everything in light, plus: claim, kill rule, predictions and queries are saved and approved before the run, and every retrieved title and abstract is screened. Strings do not change during the run; a supplemental search needs its own approval. An evidence record ([template](../templates/evidence-record.md)) keeps, for each decisive source, the version read, the SHA-256 of the PDF when one was read, the decisive quote with its page, and the retrieval date.

## 1. Write what would kill the claim

Do this before any query, because a kill rule written after seeing results bends to fit them.

1. State the claim in one plain sentence. If it is a question, write the answer it would give and what a reader could decide from it. If the answer is a number, the claim is the quantity and how it behaves, since a search cannot kill a value nobody has computed. Name any presupposition, such as "this has a cost", so the search does not treat it as settled. If the claim is too vague to be killed, stop and ask for a sharper one.
2. Split it into components: setting, decision, objective, constraints, information, claimed outcome.
3. Write the **full blocker**: a paper whose model contains ours as a special case and reports the same conclusion or quantity. It needs an explicit mapping of states, information, dynamics, actions, objective and constraints, or a derivation. Shared words or plots do not count. General theory counts only if the conclusion follows directly from it; say what remains.
4. Write the **partial blockers**: for each component, the paper that would pre-empt it and which part of the claim dies. A known component is harmless if the claim never relied on it being new. It narrows the claim if the claim's value rested on it.
5. Predict the outcome before searching. A miss is informative.
6. Search the project for earlier kill searches and novelty notes. Record their claims, dates, queries, coverage limits and unresolved candidates. Reuse evidence only where its mapping supports the present sub-claim, and assess every named lead against the current claim. An old search misses newer work, so propose searches that cover it. Readings done for another claim give anchors, not verdicts.
7. Pick the known set before any query. If the project has a bibliography (`.bib`, source table, evidence file), choose from it the entries that bear on this claim. Record the subset and how you chose it. The searches are later checked against it (step 3). A project bibliography built for a whole manuscript holds off-topic entries, so the full list is the wrong denominator.

## 2. Build queries through several lenses

The user's own sentence rarely finds the strongest rival. Rivals tend to use another field's words, so cover each lens:

- **Their words**: the user's sentence as one semantic query.
- **Application**: the field's vocabulary, as keyword and semantic queries.
- **Abstract problem**: the same problem with the application removed. Use the neighbouring field's name as the keyword query's setting block. A semantic query with no field words drifts to unrelated work, so name the neighbouring field there too.
- **Method-side neighbour**: the older field where the same structure appears under another name, such as inventory with perishability, replacement policies or stochastic processing networks. A wrong mapping finds nothing and looks like a clean result, so show the assumed mapping with the queries and ask the approver to correct it. If two mappings are plausible, cover both.
- **Adjacent application**: the nearest other application of the same decision.
- **Citation trail**, both directions, on the 3 to 5 closest papers. Run it as a second round, once screening has named them. Their reference lists (`--refs`) catch earlier work in the same community, often under words no keyword query used. Papers citing them (`--cites`) catch the newest work. Coverage of recent preprints is thin, so a zero from `--cites` means little.

Six to ten queries are usually enough. Do not build every query by AND-ing all desired features: demanding every extension word can exclude the strongest comparator. Choose date limits for the question, not a default window; include older foundational results. Other search tools the user has may add a semantic lens; record which, and treat their output as leads.

Query rules are in "Searching OpenAlex" in [search-rank.md](search-rank.md). Its question screens and ranking steps do not apply here. One exception: keep metric terms when the metric is part of the claim. Show every generated query, the assumed mapping and a cap on open-access PDFs (five by default) before running, under the authorization rule in [SKILL.md](../SKILL.md). Count previews are queries too.

## 3. Run and account for coverage

Run `$PY $PL/scripts/openalex_search.py` with `--exact`, `--semantic`, `--cites` or `--refs`, plus `--name` and a new `.jsonl` path in `--out` outside tracked files. No `literature.json` is needed. Keep the JSONL and its `.query.json` record. Report for each query the total count, the records written, the records screened and the overlap. Keyless keyword and citing searches return at most 200 records and semantic searches at most 50; disclose whichever limit applied.

- Match records against the project's source table yourself by DOI and arXiv id. The `in_sources` field is empty when no config exists, and a count of zero then means nothing.
- Under low keyword and semantic overlap, keyword queries may be missing the field's words. If `search_overlap.py` says a keyword search holds fewer works than it matched, say so first: the cut alone can lower the overlap. Propose one revised query when the only-semantic titles show missing words, or state plainly that you did not revise.
- Agree on a screening ceiling before the run; the default is 2,000 records per keyword string. A string above it is reported with its total and marked unscreened. That gap prevents confirming any related zero-blocker prediction.
- Check the searches against the known set from step 1 after each round, by DOI and arXiv id. Report the numerator and denominator. A relevant known paper that was missed shows a missing word or lens: read its title and abstract, and assess it against the claim like any other record. Retrieving every known paper does not establish recall across the unknown literature.

## 4. Screen honestly

Sort every distinct record into close, maybe, no or unresolved.

- Read at least every title, and the abstract wherever the title does not settle it. In frozen mode, read all abstracts.
- A word filter may order the reading but does not count as screening. Report records it hid as unscreened, with the query, count and filter.
- A record with no abstract and a relevant title is **unresolved**, not no. Try a second metadata source before giving up.
- Cheaper model readers may label large sets. Their labels are leads, not findings.

## 5. Read the closest papers

Read the three closest papers per claim in full where you can. Prefer the published version and note which version you read. Link preprints and extensions as one family; do not pool version-dependent guarantees.

Report a reading level for each paper: full text, named pages, abstract, title only or word search. A word search shows where to read; "the word does not occur" supports only that statement.

For each close paper, write one sentence for its result and one for our claim, compare their assumptions, and say whether the difference changes a result or a decision. Treat the whole claim as covered only when the evidence meets the full-blocker rule. Otherwise name the pre-empted component or mark the comparison unresolved. Failing to spot a consequential difference does not establish equivalence. If the user's own papers are the closest comparator, say so.

Keep downloads in a new empty folder outside the project and extract text without running anything from it. For closed papers, list the title and DOI and ask the user for the PDF. Do not work around paywalls, treat a missing PDF as absence, or guess from a title what a paper says.

## 6. Give one verdict per claim

| Verdict | Requires |
| --- | --- |
| **Killed** | A named source, the decisive passage with its page (or the quoted abstract, under the rule below), and matching assumptions and conclusion, or an explicit derivation |
| **Undecided** | No verified full blocker, but an unread candidate, unclear mapping, unscreened record or coverage gap could change the verdict |
| **Narrowed** | At least one verified partial blocker, no full blocker, nothing unresolved that could change the verdict. State the pre-empted components and the surviving claim in one sentence |
| **Stands in the searched corpus** | No verified blocker, the closest papers read, nothing unresolved that could change the verdict |

Apply the rows in this order and report the first that fits, with no "leaning" variants. An abstract can carry a kill only when it states both the conclusion and the matching assumptions; say so, and name the paper a person must still read. Under Undecided, still report verified partial blockers, without calling the remainder safe. Neither Narrowed nor Stands establishes novelty. A theorem that yields an immediate corollary kills that theorem claim but may leave a separate engineering question; assess it separately.

## 7. Label the novelty

Do this unless the verdict is Killed. The label describes the difference from the papers read; it does not replace the verdict.

1. **Facets.** For each closest paper, mark objective, method, evaluation, data, setting, claimed result, assumptions, information and dynamics as same, different or not stated. Base it on the reading level you reported, and call the label provisional when any closest paper was read only as an abstract. A changed facet or number alone establishes neither significance nor originality.
2. **Type.** Choose one and give a sentence of reason:
   - **Repeat**: the same relation under the same conditions.
   - **Consolidation**: a new relation inside one established line of work.
   - **Bridge**: it joins lines of work that the closest papers treat separately.
   - **Jump**: it adds an element absent from all closest papers.
   - **Undetermined**: the evidence read does not settle the type; name the unread passage or unresolved mapping. Use it when a closest paper was read only by title or word search, or when an unread passage or unresolved mapping could change the type. An abstract that states the relevant facets can give a provisional type.
3. **Level.** Say **novel candidate** when the idea differs from every closest paper in at least one facet or in their combination, and name the difference. Say **not novel** when a closest paper matches on all facets. Say **undetermined** when an unread paper or coverage gap could change this. A change of setting alone is novel only in that setting; say so.
4. **Original: open questions.** Mark each as holds, fails or open: not stated, not implied, consequential, backed by evidence. A search can bear only on the first two. The last two need our own result, so without one they stay open.

Give no percentage or score. Experts disagree on graded novelty, and a number would suggest a precision the search lacks.

## 8. Judge three axes

Give each axis its own value; never merge them into one overall judgement. Each value comes with its basis (the papers behind it and their reading levels) and, when it is undetermined, the one step that would settle it: the passage to read, the PDF to get, the fact to ask the user.

| Axis | Values |
| --- | --- |
| **Prior work** | **done**, **close work done**, **not found in the records screened**, **undetermined** |
| **Support in the literature** | **supporting work found**, **conflicting evidence**, **no support found**, **undetermined** |
| **Feasibility** | **feasible now**, **obstacle that can be overcome**, **serious obstacle**, **undetermined** |

- **Prior work** follows the verdict: Killed is done, Narrowed is close work done, Stands is not found in the records screened, Undecided is undetermined. Under close work done, set the closest paper's result and our claim side by side in one sentence each, and name the difference that survives. Not found is never "new" or "original".
- **Support in the literature** asks whether published work backs the claim's assumptions and mechanism, not whether the claim is true. Supporting work found names the paper and passage. Conflicting evidence names both sides. No support found means the screened records were searched for support and none turned up; undetermined means the relevant papers were not read beyond their abstracts or a mapping is unresolved. Our own result belongs to [test](test.md), not to this axis.
- **Feasibility** asks whether the work could start with what exists: data, equipment, computation, a solver that scales, assumptions that hold in practice. Base it on what the papers report and what the user states about their resources. When the resources are not known, it is undetermined; ask rather than guess.

Use undetermined whenever the evidence read does not settle an axis. An axis judged only from abstracts is marked provisional.

## Report

Answer first in plain words, then keep it short:

1. **Verdict** and the surviving claim, in plain sentences.
2. **Closest work**: at most five rows of paper, what it does, how it differs, and reading level.
3. **Novelty label**, unless the verdict is Killed.
4. **Three axes**: one line each with its value, basis and, when undetermined, the step that settles it.
5. **What this does not show**: search scope, filters, unread papers, and whether predictions held.
6. **Who must act**: the PDFs needed from the user, and which papers a person must read.

Write "not found in the records screened", never "no one has done this". Save nothing to project records unless the user or the frozen level calls for it. Delete the PDFs and text extracts this run downloaded once the report is done, keeping only what a later step will read; never delete the user's own files. In frozen mode, first copy the decisive quotes, pages, versions and hashes into the evidence record. A hash identifies the file read; it does not keep it.
