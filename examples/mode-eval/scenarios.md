# Scenarios

Status: **frozen** (`FROZEN.sha256`). The claims come from the `uw-entanglement-scheduling` lab records. Hüseyin Uğur Yıldız read each decisive passage and approved the expected outcomes on 3 November 2026. Scenario D, the positioning case, is open in [scenario-d.md](scenario-d.md).

Each run: light level, a new empty folder, a new session. Paste only the "Prompt" block.

## A. Expected Killed: transfer certificate

**Prompt**

> Has this been done? Try to kill it. Claim: for a fixed control policy that does not observe a hidden channel state, we give a transfer certificate that bounds how much the policy's long-run average cost, service rate and number of attempts change when the channel moves from independent attempts to persistent (two-state Markov) failures. With one-step kernel difference δ = 2ρ·max(g, 1−g) and the nominal chain's m-step contraction coefficient α_m < 1, every reward f satisfies |ΔJ| ≤ ½·sp(f)·min{2, mδ/(1−α_m)}. The bound itself is our contribution. Show me the queries; I will approve them.

**If asked:** approve the queries as shown; PDF cap 5; no PDFs supplied beyond what the run downloads.

**Approved:** Hüseyin Uğur Yıldız read the decisive passage and approved the expected outcome, 3 November 2026.

**Expected:** Killed. The bound follows directly from a classical perturbation bound for the stationary law of a uniformly ergodic chain: telescoping gives the m-step kernel difference ≤ mδ, and the bound applies separately to each bounded reward.

**Decisive passage:** Mitrophanov (2005), J. Appl. Probab. 42(4), DOI 10.1239/jap/1134587812, Theorem 3.2, Eq. (3.11), printed p. 1007; Eq. (3.17), printed p. 1008, for the one-step to m-step envelope. Another classical stationary-law perturbation bound counts if the run quotes it with its page and shows the same mapping.

**Fails N5 when:** Narrowed, Stands, or Undecided while the decisive passage was read; Killed without a page or with only an abstract that does not state the bound.

Source: `uw-entanglement-scheduling`, `plan/fixed-policy-transfer-claim.md` at commit `41c706f^`, item 4; notes `literature/pdfs/other/notes-full-2026-10-30.md` lines 175 to 176 (29 October 2026).

## B. Expected Narrowed: age trade-off at a hub

**Prompt**

> Has this been done? Try to kill it. Claim: at a hub node that stores entangled pairs which age over time, we compute the exact trade-off curve between age and a service-rate floor with an exact constrained MDP/LP that chooses which of two recipients gets the stored pair; the LP's dual multipliers price the service floor. Both the method and the setting are new. Show me the queries; I will approve them.

**If asked:** approve the queries as shown; PDF cap 5; supply no PDFs.

**Approved:** Hüseyin Uğur Yıldız read the decisive passage and approved the expected outcome, 3 November 2026.

**Expected:** Narrowed, or Undecided that reports the same verified partial blockers and names the record that keeps it open. The method is pre-empted: exact constrained MDPs or LPs for age under budgets or rate floors, with multipliers on the constraints. What survives: a stored resource that ages while two recipients compete for it.

**Decisive passages (any one, with page):** Sun et al. 2020, DOI 10.1109/INFOCOMWKSHPS50562.2020.9162952, Theorem 1, Sec. III-A; Kadota et al. 2019 (multipliers on throughput floors); Ceran et al. 2019 and 2021 (the same toolkit with one budget); Zakeri et al. 2023 and Zhou et al. 2025 (exact constrained MDPs or LPs for age).

**Fails N5 when:** Killed; Stands; or the method is called new.

Source: notes lines 61 to 70 (blocker search 20 October, kill search 22 October 2026). The 151 "maybe" records were judged on abstracts only.

## C. Expected Undecided: closed closest paper

**Prompt**

> Has this been done? Try to kill it. Claim: we compute the minimum entanglement-generation cost, with generation attempts, swaps and purification priced, needed for two end-user pairs that share one intermediate node to meet their delivery-rate and fidelity floors; this question is new in quantum networks. Show me the queries; I will approve them.

**If asked:** approve the queries as shown; PDF cap 5. Any PDF requested from the user: "I do not have it now; continue without it."

**Approved:** Hüseyin Uğur Yıldız read the decisive passage and approved the expected outcome, 3 November 2026.

**Expected:** Undecided. Verified partial blockers may be reported (pricing generation, swaps and purification for a rate and fidelity target is not new by itself). Gu et al. is listed as a closed paper a person must read, and the verdict is not settled from its abstract. Novelty type Undetermined, or a provisional type that names Gu et al. as the unread passage.

**Decisive passage (unread by design):** Gu et al., "Cost-Aware High-Fidelity Entanglement Distribution and Purification in the Quantum Internet", IEEE Transactions on Networking 34 (2026) 681 to 696, DOI 10.1109/TON.2025.3606263. Known outcome, for the scorer only: p. 693, §VIII, states that the main solution is for a single source-destination pair and represents scarce resources by prices, so the full text does not kill the claim.

**Fails N5 when:** Killed or Narrowed on Gu et al.'s abstract alone; Stands; Gu et al. not found or not listed for reading.

Source: `plan/aoe-service-lab/runs/narrow-search-001/RESULT.md` lines 24, 51 and 57; resolution in `three-paper-read-001/RESULT.md` lines 9 and 51 (3 November 2026).
