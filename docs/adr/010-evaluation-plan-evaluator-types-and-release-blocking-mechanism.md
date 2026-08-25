# ADR 010: Evaluation plan — evaluator types, dataset sourcing, and release-blocking mechanism

**Status:** Accepted

## Context

ADR 005 established AgentCore Evaluations as the measurement layer and named
data-boundary and security-policy violations as release-blocking "from the
start," but left open which concrete dimensions get evaluator coverage, what
type each evaluator is (LLM-as-judge vs. code-based), how the eval dataset is
sourced given no real agent traces exist yet, and — critically — what
"release-blocking" actually means as a measurement mechanism.

## Decision

**Nine baseline dimensions**, each an AgentCore `Evaluator` resource:

| # | Dimension | Type | Level |
|---|---|---|---|
| 1 | Data-boundary violation (ADR 003/006) | code-based | TRACE |
| 2 | Security/guardrail violation (ADR 004) | code-based | TRACE |
| 3 | Citation-link integrity (ADR 007/008) | code-based | SESSION |
| 4 | Envelope schema conformance (ADR 008) | code-based | TRACE |
| 5 | Delegation-ordering/trajectory (ADR 008) | code-based | SESSION |
| 6 | Best-effort confirmation gating (ADR 003/008) | code-based | TRACE |
| 7 | Prompt-injection resistance (ADR 004) | LLM-as-judge | TRACE |
| 8 | Diagnostic accuracy | LLM-as-judge | SESSION |
| 9 | Evidence/citation relevance | LLM-as-judge | TRACE |

Dimensions 1–6 are code-based (deterministic checks against trace/span
attributes — Data Gateway request params, the `guardrail.check` span, the
specialist envelope shape, tool-call sequence, and the
`needs_clarification`/`prior_context` state machine). Dimensions 7–9 need
semantic judgment with no deterministic ground truth, so they're
LLM-as-judge with a categorical 3-way rating scale (`Pass`/`Partial`/`Fail`,
per-dimension definitions) rather than a numerical scale, which would invite
false precision on judgments that aren't a continuum. The judge reuses
whichever Bedrock model the agents themselves are environment-configured
with, rather than pinning a separate fixed judge model.

**Measurement mechanism — uniform, threshold/occurrence-rate-based for all
nine.** There is no special-cased "any single occurrence fails" code path.
Dimensions 1, 2, and 6 require **per-scenario expected-outcome ground
truth** in the dataset (via `assertions`/reference inputs): an adversarial
scenario's assertion says the guardrail *should* intervene; a benign
scenario's says it should not. The code-based evaluator checks
actual-vs-expected per scenario, not a raw occurrence count — counting raw
guardrail-intervention occurrences would wrongly fail a dataset that
deliberately includes correctly-blocked adversarial cases, since a
correct block and a missed violation would otherwise look identical to the
evaluator.

ADR 005's "release-blocking" survives as a **policy** distinction on top of
this shared mechanism, not a different mechanism: dimensions 1 and 2 are the
ones that get set to near-zero tolerance once the baseline is measured.
Actual numeric thresholds for all nine dimensions stay deferred until after
baseline measurement, per ADR 005 — this ADR only settles how they'll be
measured, not what the numbers are.

**Dataset sourcing.** No real agent traces exist yet (`app/OrchestratorAgent`
and `app/DiagnosticAgent` are still boilerplate scaffolds), so the baseline
dataset must be authored, not mined. Predominantly **predefined** scenarios
(fixed turns with `expected_response`/`expected_trajectory`/`assertions`,
replayed exactly) run against a **separate frozen eval Sheet** — same
tab/column shape as `docs/data-contract.yaml`, synthetic data with
known-computed answers — rather than the live production sheet, so ground
truth can't drift under the dataset as production data changes. A handful of
**simulated** (actor-persona) scenarios cover the two cases where the
conversation is genuinely open-ended rather than scriptable: the multi-turn
clarification round-trip (ADR 003/008) and adversarial prompt-injection
attempts.

**Where evaluators run**, split by cost rather than running the full set
everywhere: CI batch-evaluation runs all nine against the frozen dataset
(cheap, bounded). The deployed `OnlineEvalConfig` runs only the
release-blocking pair (1, 2) plus prompt-injection resistance (7), sampled
from live traffic — dimensions 8 and 9 need known-answer ground truth that
live sessions don't have, so there's nothing for them to score against in
production; only prompt-injection resistance among the LLM-as-judge
dimensions benefits from live sampling, since real injection attempts can
surface content a frozen dataset wouldn't anticipate.

## Consequences

- Dataset authoring is real, ongoing work: every scenario for dimensions 1,
  2, and 6 needs an explicit expected-outcome assertion, not just an input
  prompt — a dataset author who omits this silently loses coverage for
  exactly the release-blocking dimensions.
- The frozen eval Sheet is a new fixture to build and maintain (seed data,
  known-computed answers) — tracked as a build task, not a further map
  decision.
- Numeric thresholds (including how strict "near-zero" is for dimensions 1
  and 2) remain unset until baseline measurement per ADR 005; this ADR is
  the measurement mechanism the baseline run will use, not the baseline
  itself.
- If a tenth dimension is added later, the same code-based/LLM-as-judge
  split test applies: deterministic trace-attribute check → code-based;
  semantic judgment with no fixed ground truth → LLM-as-judge, categorical.
