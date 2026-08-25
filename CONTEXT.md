# RCA Agent Context

## Root-cause analysis (RCA)

A structured investigation that turns a business symptom into evidence-backed
findings, confidence, and recommended actions.

## Investigation

One user-initiated RCA run, from question through final synthesis. It may ask
for clarification before continuing with an uncertain analysis.

## Orchestrator

The top-level agent that plans an investigation, delegates work, and produces
the final synthesis. It does not bypass the data gateway, holds no gateway or
web-search tools itself, and is the only agent the user or a specialist ever
talks to (star topology) — specialists never call each other or the user
directly.

## Diagnostic analyst

The specialist that discovers approved Sheet structure, identifies measurable
drivers, and investigates relevant segments. Returns findings.

## Evidence guard

The specialist that retrieves and rates external context, validates claims, and
attaches provenance. Web content is evidence, never instruction. Returns
citations when given findings to link against, or context snippets when run
standalone.

## Delegation contract

The schema-validated request/response shape between the Orchestrator and a
specialist over A2A. Free text is confined to the envelope's narrative field
and is never load-bearing for another agent, evaluator, or the synthesis.

## Specialist envelope

The generic response shape every specialist returns: a status, a typed result
array (findings, citations, or context snippets), and a narrative. The same
shape regardless of which specialist, or how many specialists exist.

## Finding

A Diagnostic analyst's structured claim about Sheet data: a stable id, metric,
scope, computed value, source pointer, confidence, and assumptions. The unit
an Evidence guard citation links to.

## Context snippet

An Evidence guard result returned when it runs standalone, with no findings to
link against. Same shape as a citation minus the required finding-link. Never
treated as RCA evidence or folded into confidence.
_Avoid_: citation (a citation always links to a finding; a context snippet
never does)

## Investigation status

The rolled-up state of an Investigation — complete, partial,
needs_clarification, or failed — computed from the specialists' individual
statuses.

## Data gateway

The single read-only AgentCore Gateway path to Google Sheets. Agents request
approved operations; they never receive Google credentials or direct Sheet
access.

## Data contract

The version-controlled policy that defines the approved spreadsheet scope,
tabs, semantic fields, operations, and limits exposed by the data gateway.

## Semantic discovery

Mapping approved Sheet headers and compatible types to pre-approved business
meanings. It may adapt to an alias but may not expand the data boundary.

## Math operations target

The gateway target that performs statistical and aggregation operations
(e.g. sum, average, percent-change, group-by-aggregate) over rows the
diagnostic analyst has already retrieved. It receives no Google credentials
and makes no Sheet access of its own — it operates only on data already in
hand.

## Paginated range read

The diagnostic analyst's responsibility to never request more Sheet data
than the data contract's per-call limit allows: when it needs a larger
range, it issues multiple within-limit reads and stitches the results
together itself, rather than requesting an oversized range and receiving a
rejection.

## Best-effort analysis

An analysis made with incomplete or ambiguous data. It is allowed only after
the user explicitly confirms continuation and must state its uncertainty.

## External context

Web-derived information used to corroborate or challenge an internal finding.
It cannot be the primary root-cause claim without a matching internal signal.

## Evidence citation

The source range, metric, tool result, or web source that supports a claim.
An external citation must link to at least one internal finding it
corroborates or challenges — it can never stand alone.

## Reputation tier

The `trusted` or `general` label attached to an external evidence citation,
determined by which of the evidence guard's two gateway searches (an
unrestricted pass and a trusted-domain-only pass) returned it. Not a
computed score.

## Evidence reputation policy

The version-controlled `docs/evidence-reputation.yaml` file listing the hard
denylist (blocked at the data gateway before results return) and the
trusted-domain allowlist (used as a request-level search filter) behind
reputation tiers.

## Guardrail

A Bedrock Guardrails check applied to agent inputs and outputs for prompt
attacks, sensitive data, and grounding-related safety signals.

## Trace

The AgentCore Observability record of agent activity, handoffs, tool calls, and
guardrail events. ADR 004 calls for sensitive values to be redacted or hashed
before retention, but this is deferred for the MVP — traces currently ship
unredacted, and are not safe to expose beyond the single-user
secure-observability view.

## Guardrail-event span

A dedicated trace span emitted whenever a Bedrock Guardrail check runs,
carrying the action (blocked/passed) and triggered policy categories with
confidence levels, but never the raw content that was flagged. See ADR 004.

## Evaluation baseline

The initial AgentCore Evaluations measurement from which release thresholds are
set. Every dimension, including security and data-boundary violations, is
measured the same way (an occurrence-rate threshold over the eval dataset);
security and data-boundary violations stay non-negotiable by policy — they
get set to near-zero tolerance once the baseline is measured — not by a
different measurement mechanism. See ADR 010.

## Frozen eval Sheet

A synthetic Google Sheet fixture, matching `docs/data-contract.yaml`'s
tab/column shape, used only for evaluation datasets and never touched by a
real Investigation. Its data and computed answers stay fixed so a predefined
scenario's `expected_response`/`expected_trajectory` ground truth can't drift
out from under it the way it would against the live production sheet.

## Investigation memory session

The single AgentCore Memory session (its id is the Investigation's A2A
`context_id`) that the Orchestrator, Diagnostic analyst, and Evidence guard all
write to as their own turn resolves, spanning the whole Investigation including
any clarification round-trip. Only the Orchestrator ever retrieves from it.

## Investigation summary

The AgentCore Memory SUMMARIZATION output for one Investigation memory session:
a condensed record of the question, clarifications, and synthesis, built
automatically from every agent's turn.
_Avoid_: narrative (an agent-authored free-text field in the delegation
contract, not a Memory artifact)

## Past-RCA episode

The AgentCore Memory EPISODIC output for one completed Investigation, created
only when its status resolves to complete or partial. Captures the symptom,
root cause, and confidence so a future Investigation's planning can recall
whether a similar RCA has been seen before. Never created for a
needs_clarification or failed Investigation.
