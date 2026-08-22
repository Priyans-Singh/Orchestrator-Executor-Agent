# ADR 001: Start with a narrow, observable three-agent RCA MVP

**Status:** Accepted

## Context

The project must demonstrate both reliable business diagnosis and secure
multi-agent engineering without starting as a broad analytics platform.

## Decision

Build a chat-style MVP for a single user investigating business-performance
changes. Use three top-level agents:

1. An orchestrator for planning, delegation, and synthesis.
2. A diagnostic analyst for approved internal Sheet data.
3. An evidence guard for external context and claim verification.

The UI will stream investigation progress and expose AgentCore Observability
traces, including agent and subagent activity, handoffs, tool calls, and
guardrail events. It will expose structured rationales and evidence, not private
chain-of-thought.

## Consequences

- The first version optimizes for a demonstrable vertical slice rather than
  broad KPI coverage.
- External context is in scope but belongs to the evidence guard.
- Future specialization can add agents without changing the core trust boundary.
