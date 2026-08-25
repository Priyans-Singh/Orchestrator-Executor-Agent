# ADR 008: Orchestrator-specialist delegation contract, generic envelope, and synthesis ownership

**Status:** Accepted

## Context

ADR 001 named three agents and gave the Orchestrator planning, delegation, and
synthesis, but left the actual A2A contract open: who may talk to whom, what
the delegation request/response looks like, how progress and clarifying
questions flow mid-Investigation, and how the final result is assembled from
specialist outputs. ADR 007 already required every Evidence Guard citation to
link to an internal finding id, which implicitly requires Diagnostic analyst
output to be structured, not prose — but assumed Evidence Guard always runs
after the Diagnostic analyst, leaving no path for a standalone external-only
question.

## Decision

**Topology — star.** The user talks only to the Orchestrator. The Orchestrator
talks to each specialist. Specialists never call each other and never reply to
the user directly.

**Delegation rule — hard split by capability.** The Orchestrator holds no
Data Gateway or web-search tools itself. Anything needing Sheet data is a
Diagnostic analyst task; anything needing the web is an Evidence Guard task.
The Orchestrator's own work is conversation, planning, and synthesis.

**Transport — A2A `message/send`/`message/stream`, JSON-RPC, unchanged.**
AgentCore Runtime passes A2A JSON-RPC through unmodified, so this is standard
usage, not a deviation. Specialists emit intermediate `TaskUpdater` status
frames as they work (e.g. "reading Sheet tab Performance"); the Orchestrator
relays each as a progress event on its own outbound stream to the user's UI,
per ADR 001's "UI will stream investigation progress." A 60-second poll
(`tasks/get`) was considered and rejected — most single-specialist tasks
finish faster than that window and a poll would show one lurch instead of real
progress.

**Trace propagation — headers and baggage, not payload fields.** AgentCore
Runtime auto-instruments agents with OpenTelemetry; standard OTel HTTP
instrumentation already injects/extracts the W3C `traceparent` header on every
A2A hop, so nested spans line up in CloudWatch GenAI Observability with zero
application code. No `traceParent`/`traceId` field belongs in the message
schema — that would be a redundant, driftable duplicate of what the transport
already does. Cross-agent session correlation instead uses OTel baggage keyed
on the same `context_id` already in the request schema below.

**Delegation request schema** (Orchestrator → specialist):

- `task_id`, `context_id` — reused across the clarification round-trip and the
  whole multi-turn Investigation; map to A2A's `taskId`/`contextId`.
- `objective` — free-text instruction: what's being delegated and why.
- `scope` — structured hints to stay inside: metrics/segments/time range for
  the Diagnostic analyst; the search topic plus `findings[]` to try to
  corroborate/challenge for Evidence Guard (may be empty — see standalone
  case below).
- `prior_context` (optional) — the user's answer from a prior clarification
  round, present on a retry delegation.

**Specialist envelope** (specialist → Orchestrator) — one generic shape every
specialist returns, independent of which specialist or how many exist in the
future:

- `status`: `complete` | `partial` | `needs_clarification` | `failed`.
  `partial` (a best-effort result) is only legal on a retry that already
  carries the user's ADR-003-required continuation confirmation in
  `prior_context`; a first pass that would need best-effort returns
  `needs_clarification` with `clarifying_questions[]` instead, making ADR
  003's "ask before best-effort" rule a mechanical consequence of the state
  machine.
- a typed result array — see below.
- `narrative` — free text for anything the typed fields don't capture. Never
  load-bearing: no other agent, evaluator, or synthesis step depends on
  parsing it. This is what keeps the contract generic enough to later accept
  registry-discovered specialists without hardcoding their private fields —
  only the envelope shape is a shared assumption.

**Diagnostic analyst's typed result — `findings[]`.** Each item: `id`
(stable within the Investigation; the anchor Evidence Guard's citations link
to), `claim`, `metric` (a `docs/data-contract.yaml` semantic field), `segment`
(nullable), `time_range`, `value`, `basis` (source tab/range/operation
pointer — distinct from the trace copy ADR 004 redacts), `confidence`, and
`assumptions[]` (free text, e.g. alias mappings or best-effort caveats).

**Evidence Guard's typed result — `citations[]` or `context_snippets[]`,
never both in one response.** When `findings[]` was non-empty in the request,
Evidence Guard returns `citations[]` exactly as ADR 007 defined: every item
required to carry a non-empty `corroborates_finding_id`/`challenges_finding_id`
link. When Evidence Guard runs **standalone** (no findings — a pure
external-context question that never touched the Sheet), it returns
`context_snippets[]` instead: the same fields minus the finding-link
requirement. This amends ADR 007's scope, which assumed Evidence Guard always
follows the Diagnostic analyst. The Orchestrator never treats a
`context_snippet` as RCA evidence and never folds it into `overall_confidence`
or a recommended action's justification — ADR 004's "external content cannot
establish a primary root-cause claim" is enforced structurally by which array
a result lands in, not by convention.

**Delegation ordering.** Sequential, never fan-out, whenever both specialists
are needed: Diagnostic analyst first, because Evidence Guard's citations
depend on finding ids that don't exist yet. The Orchestrator itself calls
Evidence Guard in both the sequential and standalone cases — the Diagnostic
analyst never calls Evidence Guard directly, preserving the star topology.
Evidence Guard is not required to run at all when a question needs no
external context.

**Clarification round-trip.** A specialist's `needs_clarification` (with
`clarifying_questions[]`) is surfaced to the user as the Orchestrator's own
reply — the Orchestrator still authors all user-facing text, never a raw
pass-through. The user's answer arrives next turn; the Orchestrator
re-delegates to the same specialist reusing `task_id`/`context_id`, with the
answer in `prior_context`.

**Synthesis — Orchestrator-authored only.** The final result assembles
`findings[]` and `citations[]`/`context_snippets[]` unmodified from the
specialists, plus Orchestrator-authored `narrative` (not concatenated from
specialist narratives, which stay internal) and `recommended_actions[]`
(never sourced from a specialist). `overall_confidence` is computed, not
copied: the **lowest** contributing finding's confidence caps the
Investigation's overall confidence, rather than an average, so one weak
finding can't be hidden by averaging. `investigation_status` rolls up from
the specialists' individual statuses — any `needs_clarification` makes the
whole Investigation `needs_clarification`.

## Consequences

- Specialists must emit intermediate `TaskUpdater` status frames mid-run, not
  just a final artifact — a real implementation obligation on both scaffolds
  (`app/OrchestratorAgent`, `app/DiagnosticAgent` currently only call
  `add_artifact` once).
- The envelope's genericity means adding a future specialist never requires
  changing the Orchestrator's parsing logic, only the new specialist's own
  typed result array.
- ADR 007's "every citation requires a finding link" now applies only when
  Evidence Guard has `findings[]` to work with; the standalone case is a
  distinct, explicitly non-evidentiary output type.
- Evaluators (map ticket for the evaluation plan) can validate against one
  stable envelope shape instead of per-specialist ad hoc parsing.
- `overall_confidence`'s "lowest caps overall" rule is a genuine judgment
  call, not a mechanical necessity, and may need revisiting once real
  Investigations are observed.
