# Discover

Keep topic discovery cheap, structural and honest. Turn a field or a set of papers into a few questions worth testing. The output is a lead with evidence and a test plan, not a declaration that an idea is original or publishable. An unknown answer is a reason to investigate; discovery does not need an already demonstrated gain.

## Choose the entry

- **Assumption-first**: the researcher knows a toolbox and is entering a field. Use it when there are few papers in hand. See below.
- **Corpus-first**: the researcher has PDFs. Use it to compare methods and find what cannot yet be answered. See below.

Both end at the same place: a candidate card, a closest-work check, and the smallest useful test.

## What counts as a contribution

Ask what a reader could learn or decide after this study that the closest work does not already establish.

| Route | Possible new knowledge | Insufficient by itself |
| --- | --- | --- |
| Common modelling and comparison | Comparable costs, feasible regions or design choices across separate methods | New notation or a collection of summaries |
| Optimization and system design | Trade-offs, bounds, bottlenecks, the value of information | A standard solver on a renamed problem |
| Transfer or combination | A justified adaptation that answers an unresolved question | Adding a known technique without a reason it helps |
| Empirical or computational evaluation | Evidence on generalization, ranking stability or failure conditions | More parameter plots without a question |
| Structural or negative result | Equivalence, sufficiency or impossibility that simplifies a decision | An isolated toy observation presented as general |

"Nobody combined A, B and C" is a gap statement, not yet a contribution. An empty cell in a coverage table may be untried, uninteresting or physically impossible, and the table cannot tell which. A result that changes a number, a ranking or a decision counts; it need not change the shape of a solution.

## Assumption-first

1. **Start from a breaking assumption, not from the literature.** Which standard model in the researcher's toolbox changes under this field's physics or rules, and how?
2. **Learn the decision model.** Build or commission a short, cited account of the field's resources, decisions, dynamics, objectives and information, the canonical formulations, and a table of standard models: transfers, transfers with a changed assumption, does not transfer. The middle column is where candidates come from.
3. **Write the problem card** ([template](../templates/problem-card.md)). The researcher owns the question and the claim. AI may sharpen the card and may propose ideas, each labelled speculative, because ideas from AI tend to sit close to existing work.
4. **Name the partner parameters.** List the measurable values the model cannot be formulated without, and who could supply them. A proposal that depends on a field's physics needs someone who owns that physics; say so plainly when nobody does.

## Corpus-first

1. **Inventory the papers** by title, identifier, version and what was read: full paper, named pages, abstract or secondary summary. Deduplicate versions, keeping material differences.
2. **Extract one row per method**, with locators:

| Method and locator | Problem and mechanism | Decisions and information | Resources, timing, assumptions | Output, guarantee, limits |
| --- | --- | --- | --- | --- |

   Keep measurements, simulations, mathematical results, adopted assumptions and your hypotheses distinct. An author's future-work sentence is a lead; read later work before treating it as open. Missing data stay unknown. Never simulate having read a PDF.
3. **Build a faithful common abstraction**: mechanism, then abstract state or constraint, then controllable decision, then measurable consequence. Say what it preserves and discards. Choose the mathematical family after identifying the decision. Set the comparison contract in [test.md](test.md) before suggesting performance comparisons.
4. **For an analogy**, record concrete purpose, abstract purpose, mechanism and indispensable constraints for source and target. Write the bridge: the relation carried over, the adaptation needed, one condition that would break it. Shared purpose is a reason to investigate, not evidence that transfer works. Classical equivalence may supply a comparator or proof; decide separately whether a target-specific question remains.
5. **Generate six to ten short candidates** across several routes, each labelled speculative. Merge those that differ only in technique names or parameters. Useful prompts: Which methods cannot yet be compared fairly? Which assumption limits a consequential conclusion? Which trade-off is unknown? What would showing that a simple method suffices teach us?
6. **For learning methods**, name the task, data, observability and the reason learning could help, a strong non-learning comparator, costs and leakage-free splits. Do not insert learning to make a proposal sound new.

## Eliminate and choose

Give each serious candidate: the closest work by question, mechanism, information, objective and outcome (run [novelty-check.md](novelty-check.md) when it needs more than a quick look), the strongest simple explanation, the main failure mode, and a finding that would defeat it. A fallback question gets its own record and check; it inherits nothing.

Sort into **test next**, **verify a named fact first** or **drop or reframe**. Then compare the leading candidates pairwise, with the deciding reason, the evidence, and what would reverse the choice. Use no scores. Preserve ties when evidence does not separate candidates. Return up to three materially different candidates, or fewer, or none: "this corpus supports no strong candidate" is a valid result.

Use the candidate card in [problem-card.md](../templates/problem-card.md). Record rejected candidates with a reason and a trigger for revisiting. Stop when the remaining uncertainty needs missing evidence or an experiment; do not keep generating variants to obtain a positive verdict.

## Report

Lead with the recommended candidate or the unresolved trade-off, then scope and reading coverage, the shortlist, and one concrete next action that obtains the next piece of evidence. Say whether a stated value of the work is sourced or assumed. Time-box: if discovery is turning into a literature governance project, stop and pick the smallest test.
