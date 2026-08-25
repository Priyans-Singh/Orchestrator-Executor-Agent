# ADR 009: AgentCore Memory strategy selection and multi-agent write model

**Status:** Accepted

## Context

ADR 008 settled the Orchestrator-specialist delegation contract but left AgentCore
Memory itself open: which of the four managed strategies (SEMANTIC, SUMMARIZATION,
USER_PREFERENCE, EPISODIC) this system needs, what each stores, and how Memory
interacts with a multi-turn Investigation's clarification round-trip.

## Decision

One shared Memory resource (`MEMORY_ID`) for all three runtimes — this is a
single-user MVP (ADR 001), so `actorId` is fixed; `sessionId` is the Investigation's
A2A `context_id`, spanning the whole clarification round-trip.

**All three agents write directly to the shared session**, not just the
Orchestrator. As each agent's turn resolves, it writes its own full contribution
as a Memory event: the Orchestrator writes the user's message and its own
synthesis narrative; the Diagnostic analyst and Evidence Guard each write their
full delegation response (`findings[]`/`citations[]`/`context_snippets[]` plus
`narrative`). This is a deliberate side-channel alongside the A2A envelope, kept
narrow: it never feeds data back into another agent's context, and no specialist
ever reads another agent's memory event. **Retrieval stays Orchestrator-only** —
it queries Memory during planning and folds relevant results into the
`objective`/`scope` it hands a specialist; specialists never call
`retrieve_memory_records` themselves.

Only two strategies are enabled for the MVP:

- **SUMMARIZATION** — automatic, per-session (per Investigation) summary built
  from the full turn-by-turn event stream across all three agents, so a later
  clarification round-trip in a long Investigation doesn't require resending
  full history.
- **EPISODIC** — one episode per Investigation, but only when
  `investigation_status` resolves to `complete` or `partial`. A
  `needs_clarification` or `failed` Investigation produces no episode — there's
  no RCA outcome worth recalling. Namespaced per actor
  (`investigations/{actorId}/episodes/{sessionId}`, reflections at
  `investigations/{actorId}/reflections`), giving the Orchestrator a "have we
  seen a similar RCA before" recall source during future planning.

**SEMANTIC and USER_PREFERENCE are out of scope for the MVP.** ADR 003's
schema-alias-mapping recording stays in its existing mechanism (the discovery
record alongside the data contract), not duplicated into Memory. There's no
personalization surface yet for USER_PREFERENCE in a single-user system.

## Consequences

- Specialists gain a second, narrow communication path (Memory writes) beyond
  the A2A envelope; this must stay write-only and non-load-bearing for anything
  but the (Orchestrator-only) extraction/retrieval pipeline.
- `agentcore.json`'s `memories` entry needs one `Memory` resource with
  `strategies: [SUMMARIZATION, EPISODIC]`; SEMANTIC/USER_PREFERENCE can be added
  later in place without disruptive rework.
- All three runtimes need the `MEMORY_ID` env var and `CreateEvent` data-plane
  permission; `RetrieveMemoryRecords` is only strictly required for the
  Orchestrator's execution role.
- If this system ever becomes multi-tenant (explicitly out of scope per
  ADR 002), the `{actorId}`-templated namespaces already used here mostly
  transfer without redesign.
