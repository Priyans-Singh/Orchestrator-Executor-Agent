# ADR 011: Selective control with Jev for bounded decisions

**Status:** Accepted

## Context

ADR 008 already treats the model as "environment-configured, evaluated rather
than baked into architecture" — every specialist decision today goes through
the same strong Bedrock model, whether the decision is a bounded classify/
route/score call or genuine free-text generation. Two decision points in the
backlog are bounded-choice shaped, not generation shaped:

- **Alias mapping / best-effort gating** (ticket: Semantic discovery and
  best-effort gating) — "does this renamed header match a pre-approved
  semantic field?" and "is evidence sufficient, or must this fall back to
  `needs_clarification`?" Both have a fixed candidate set and a real/derived
  confidence, no prose required.
- **Evidence Guard invoke/skip and ordering** (ticket: Sequential specialists
  and standalone snippets) — "does this question need external context at
  all?" Also a fixed action set (invoke Evidence Guard / skip it), no prose
  required.

Jev (TypeSafe AI, RLCD-trained "System One" model, GA September 2026) returns
typed `Choice`/`Score`/`Boolean` outputs with calibrated probabilities instead
of generated text, at ~70–500ms latency. The REFLEX architecture
(arXiv:2609.26532) uses exactly this shape as a fast decision layer in front
of a strong LLM, escalating only on low confidence or when free-form
generation is actually required, and reports ~70% fewer strong-model calls
with success held within a small non-inferiority margin.

## Decision

Use Jev as the decision layer for the two bounded-choice points above; keep
the existing Bedrock Claude model reserved for genuine generation (synthesis
`narrative`, `recommended_actions[]`, and `clarifying_questions[]` text) and
for any case the ReAct-style multi-step reasoning is actually required.

- **Semantic discovery / best-effort gating ticket:** alias-vs-reject header
  classification and the sufficient-evidence-vs-`needs_clarification` call are
  Jev `Choice`/`Score` calls against the fixed candidate set (pre-approved
  semantic fields; envelope statuses). The strong model is not invoked for
  these two decisions.
- **Sequential specialists ticket:** the Orchestrator's "does this question
  need Evidence Guard?" call is a Jev `Boolean` decision before delegation
  ordering is applied.
- **Fallback:** if the Jev credential/endpoint is not configured in an
  environment, both tickets fall back to the existing strong-model call for
  the same decision — Jev is an optimization, not a new hard dependency for
  correctness. No acceptance criteria on either ticket require Jev
  specifically; they require the *decision*, however it's made.
- Everything already decided by plain code (envelope schema/status-transition
  validity, data-contract policy gating, citation/snippet exclusivity) stays
  plain code — Jev is for decisions previously routed through the strong
  model, not a replacement for deterministic validation.

## Consequences

- A new external dependency (TypeSafe Jev API) is introduced, gated behind an
  optional credential; wiring it (API key credential provider, env var) is an
  implementation detail of the two tickets above, not a new ticket, since the
  fallback path makes it non-blocking.
- Reduces strong-model calls on the hot classification/routing path without
  changing the specialist envelope or delegation contract from ADR 008.
- If Jev's early-access API changes materially, the fallback path means the
  two tickets keep working on the strong model alone.
