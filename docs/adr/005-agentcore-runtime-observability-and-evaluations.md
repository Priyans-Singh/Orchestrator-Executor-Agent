# ADR 005: Standardize on AgentCore Runtime, Observability, and Evaluations

**Status:** Accepted

## Context

The project should make its multi-agent behavior inspectable and measure
reliability continuously during development and after deployment.

## Decision

Run the orchestrator and specialists on AgentCore Runtime. Use AgentCore
Observability for investigation traces and AgentCore Evaluations for local
development workflows, CI, and deployed runs. Establish the first evaluation
baseline before setting numerical quality thresholds.

Data-boundary and security-policy violations are release-blocking from the
start. Diagnostic accuracy, evidence quality, and trajectory thresholds are set
after baseline measurement.

## Consequences

- Development-time evaluations require the AgentCore/AWS telemetry path; they
  are repeatable but not fully offline.
- Evaluation datasets must cover both known RCA outcomes and adversarial safety
  cases.
- Model selection remains environment-configured and is evaluated rather than
  embedded in the architecture.
