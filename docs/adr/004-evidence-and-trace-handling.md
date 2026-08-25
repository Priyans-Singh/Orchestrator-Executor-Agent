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

**Amendment (redaction deferral and trace schema, resolved while designing
trace/observability implementation):** AgentCore Observability has no
platform-level redaction feature, and the AWS Distro for OpenTelemetry (ADOT)
Collector — the one place a masking processor could otherwise live — is
explicitly unsupported for AgentCore-hosted agents. Strands' own docs confirm
the SDK does not natively redact telemetry either. The only place redaction
could happen is a custom OpenTelemetry `SpanProcessor` registered on a
`TracerProvider` passed into `StrandsTelemetry(tracer_provider=...)`, run
in-process before spans reach the exporter.

Redaction remains the destination this ADR describes, but is **deferred for
the MVP**: traces ship unredacted, including business-metric values, the
spreadsheet identifier, and any credential-shaped strings that happen to flow
through traced code paths. This is an explicit scope cut for a
demonstration/personal project, not a reversal of the original judgment that
production use would need it. The mechanism above (a shared `SpanProcessor`
wired through each agent's `StrandsTelemetry`) is how it would be built when
picked back up; the still-open sub-decision is the hash-vs-strip policy per
field type.

Guardrail events get a dedicated custom span rather than relying solely on
the default `stop_reason == "guardrail_intervened"` signal on the
model-invocation span, since that default carries no policy detail. Emitted
via a Strands `HookProvider` (the same shape as Strands' documented
shadow-mode guardrail example) reading the Bedrock guardrail assessment data:

- Span name: `guardrail.check`, linked to the model-invocation span it
  accompanies.
- Attributes: `guardrail.id`, `guardrail.version`, `guardrail.source`
  (`INPUT`/`OUTPUT`), `guardrail.action` (`NONE`/`GUARDRAIL_INTERVENED`),
  `guardrail.triggered_policies` (a list of `{policy_type, category,
  confidence}` entries, e.g. `contentPolicy/VIOLENCE/HIGH` — category labels
  only, never the flagged text), `agent.name`.

Handoff spans (Orchestrator → specialist A2A calls) and tool-call spans (Data
Gateway reads, math-ops calls) use Strands/AgentCore's default
auto-instrumentation as-is — the W3C `traceparent` propagation ADR 008
already relies on makes an explicit custom handoff span redundant, and the
default tool-call span shape (`gen_ai.tool.name`, `gen_ai.tool.call.id`,
result in `gen_ai.choice`) needs no customization while redaction is
deferred.

## Consequences

- The final result distinguishes internal evidence from external context.
- Guardrails complement, rather than replace, gateway authorization.
- Trace redaction is deferred, not designed away: the MVP's traces are not
  safe to expose beyond the single-user secure-observability view assumed
  here, and shipping to any less trusted audience requires building the
  `SpanProcessor` and settling the hash-vs-strip policy first.
- The guardrail-event span is the one piece of custom trace instrumentation
  this MVP does build, since it's cheap (a hook, not a redaction pipeline)
  and is the only way to see *why* a guardrail fired without reading raw
  flagged content.
