 # ADR 004: Keep external evidence subordinate and protect traces

**Status:** Accepted

## Context

External web content is useful for business context but is untrusted. Detailed
multi-agent traces are valuable for demonstration and debugging but may contain
sensitive business values.

## Decision

Allow broad web search with source-reputation scoring and citations. Treat all
retrieved content as untrusted data. It may corroborate or challenge an
internal finding but cannot establish a primary root-cause claim without a
matching internal signal.

Use Bedrock Guardrails for each agent. Redact or hash sensitive fields before
AgentCore Observability trace retention. Keep the trace available for the
single-user secure-observability view.

## Consequences

- The final result distinguishes internal evidence from external context.
- Trace design must include explicit redaction tests.
- Guardrails complement, rather than replace, gateway authorization.
