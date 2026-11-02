# Test

Turn one idea or result into a decision: continue, revise, stop the specified claim, or remain inconclusive. There are two tracks. Pick the one that matches where the work stands, and do not force a task through every step.

- **Exploratory pilot**: there is an idea and no result yet. Build the smallest model, look at the output, find a trend.
- **Claim test**: there is a result or a stated claim. Find out what it establishes.

An assessment does not authorize an experiment, solver campaign, training run or paid run. Without authorization, finish the analysis and give an executable plan. A direct request to run a small pilot authorizes that pilot: one script and a small sweep. Anything longer, larger or paid needs its own approval.

## Comparison contract (both tracks)

Fix this before comparing anything:

1. Same task, service target, horizon, initial state and terminal cost.
2. Resource accounting, including idle operation, storage and computation. Attempts, time, energy and money stay separate unless a conversion is justified.
3. Matched information. State who knows what, when, and with what delay. A policy may use only the declared observations. A solution using future outcomes is a bound, not a competitor.
4. Compatible denominators and parameter evidence. Do not assemble one "measured" system from incompatible experiments.
5. Deliberate differences named. An architectural difference may be the treatment; account for its cost rather than erasing it.

The strongest simple baseline belongs in the comparison, including adapted rules from the closest papers. A win over weak baselines shows little.

## Exploratory pilot

A pilot is disposable: one folder, one script, one README, one figure. No phase gates or manifests.

1. **State the question and scope first**, and the idea's assumptions. Label synthetic parameters as synthetic in the code, README and figure caption.
2. **Use the smallest instance that can show the effect**: a few nodes, a short horizon, deterministic first. Use the researcher's existing solver.
3. **Three models, same script, same data, same objective:** `full` with the new feature; `reduced`, identical without it; and `simple`, the strongest adaptive rule a reviewer would propose. Without `reduced` you cannot isolate the feature; without `simple` you cannot say the optimization was needed.
4. **Sweep only** the two or three parameters that control the feature's strength. The point is where things change, not the whole surface.
5. **Check validity at a proportionate level:** feasibility of every baseline, a trivial instance solved by hand, an objective moving the right way, solver status printed, metric signs tested on a known better and worse pair. Agreement between two solvers on one shared transition builder does not validate that builder.
6. **Look at the results, then state what you see.** Report it as descriptive, marked as read after the results. Record what was tried, including failed attempts. Do not add features to bring back a gap; a new feature is a new question.

Report the question, the parameter table, the result in a few sentences, and the next step: continue, revise, stop or inconclusive. If the size is growing past a few days, shrink or stop. A simple rule that suffices is a useful result: consider the characterization or negative finding rather than rescuing the idea.

Exploratory results may support explicitly descriptive claims. To go further, use the claim-test track.

## Claim test

### 1. State the claim

Write who needs the answer, the scope, what decision or knowledge would change, and the assumptions, units, timing and target definitions that matter. Separate a useful question, a formulation, an implemented model, an observed result and a publication claim. Record what was already seen.

### 2. Check the closest answer

Compare by decision, resources, objective, information, dynamics and guarantee. Associate each decisive cell with a page or equation, or mark it unresolved. For a kill search, use [novelty-check.md](novelty-check.md). Check the combined claim as well as its components: known ingredients neither prove nor disprove a useful interaction.

Report the applicable findings, scoped to what you inspected: supported within stated assumptions; already established, with the mapping; contradicted, with the assumption or counterexample; repairable, with the narrower claim; unresolved, with the smallest next check. Assess correctness, originality and value separately. Lack of access, lack of proof and evidence against a claim are different things. Do not invent a defect to look critical, or hunt errors to save a favoured idea.

### 3. Establish a trustworthy baseline

Before interpreting an effect, check what could change its meaning: hand cases, invariants, independent calculations, residuals, uncertainty or certificates, in proportion. A solver success flag, reviewer agreement or a filename is not validation. Write the order of observation, action, execution, outcome, release, ageing, expiry and cost accrual; check boundaries and initial conditions.

For a sequential decision model:

- Separate simulator truth from controller knowledge. Action masks may use only declared observations. Feasible masks do not prove service or optimality.
- Track occupancy at the declared release boundary. Never reuse consumed resources or borrow future supply. Distinguish objective age, physical age and information age. For a claimed resource effect, show that the constraint binds.
- For minimization, a globally solved matching clairvoyant optimum can bound causal performance from below; a feasible incumbent alone cannot. Report solver status, bound, gap and unresolved cases. A finite sample-path bound does not certify an infinite-horizon average.
- Derive a tiny event tree independently of the transition builder. Check zero and one success limits, full and empty resources, expiry boundaries and consumption on failure.
- When comparing actions, use common information states and account for ties. Use paired traces with a declared coupling; an identical seed may not couple policies that draw differently.

### 4. Challenge the simple explanation

Write the strongest simple explanation and what observation would distinguish it from the proposed mechanism. Ask first whether existing evidence already answers part of the test: a valid certificate, identity or bound may remove a solve.

| Question | Smallest useful control | What it cannot establish |
| --- | --- | --- |
| Does a requirement need more resource? | The same system with and without it, other targets fixed | The mechanism or novelty |
| Is a gain explained by more work, data or energy? | Account for the input; compare at a justified common budget | Value outside that budget |
| Do equal aggregate outputs mean equal quality? | Fix outputs and cost, then bound the quality over feasible policies | Causal effects in observed data |
| Is a gain an artefact of data or evaluation? | Matched timing, a credible comparator, data not used to choose the claim | Generality beyond the design |
| Is the full model needed? | A valid simpler model or an explicit reduction | Absence of the question elsewhere |

Matching on an outcome can introduce bias in causal or empirical work. Never infer multiple optima from one value above a bound.

### 5. Fix the outcomes, then run

Write the stop rule first: the scope, inputs, comparison and what each outcome would mean. Confirmatory empirical claims need outcomes fixed before testing, on observations not used to select the claim. Theoretical claims need proof; a verified counterexample may establish a negative theoretical result without new observations, within its domain. Use meaningful effect or precision requirements justified by the question; invent no universal cutoff, and do not pick a threshold after looking.

If the results are already seen, or a subregion was chosen after looking, say so: what exists is descriptive. Test the claim on new instances with the rule written first. When a claim has parts, give each part its own outcome.

| Outcome | Meaning |
| --- | --- |
| **Continue** | The control separates the claim from the named simple explanation, within its scope |
| **Revise** | A simpler explanation or equivalent model accounts for it; keep any separate useful result |
| **Stop this claim** | A reliable contradiction or matching prior result defeats it; say which claim stops, not the whole project |
| **Inconclusive** | Failed validation, poor precision, inaccessible evidence or a non-discriminating control |

A null result, equivalence, useful simple rule or feasibility boundary can be informative. Missing evidence is unknown, not zero. Do not try variants until a favourable result appears.

## Report

Lead with the supported conclusion and what it means. Separate technical correctness, decision relevance, physical validity and literature originality. Keep configuration, code revision, observations and validation with the result, and use the [evidence record](../templates/evidence-record.md) when a durable record helps. End with one bounded next action. A small success does not authorize a campaign.
