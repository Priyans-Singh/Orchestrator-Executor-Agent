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

**LangGraph implementation amendment (issue #17):** The agents remain LangGraph.
The Orchestrator uses the shared environment-configured Bedrock Guardrail via
`ApplyGuardrail` at its input/output boundary. A current-context OpenTelemetry
`guardrail.check` span covers each request; no Strands hook or framework
migration is required. The same check/span implementation accepts a specialist's
agent name without changing the shared policy ID or version. Wiring specialist
runtimes is deferred beyond this ticket's Orchestrator delivery boundary.

`guardrail.triggered_policies` is a JSON-encoded array containing only policy
type, category, and confidence when the assessment supplies it. Grounding
scores are not confidence levels. Custom words, regexes, and denied topics use
fixed category labels rather than configured strings. Detected policies are
included when observing without blocking. Failed API checks emit an error
status and action `ERROR`, without provider exception text. Default handoff
and tool-call instrumentation is unchanged; trace redaction remains deferred.

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
