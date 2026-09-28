# EvidenceGuard

An A2A (Agent-to-Agent) agent deployed on Amazon Bedrock AgentCore using LangChain + LangGraph.

## Overview

This agent implements the A2A protocol using LangGraph. It makes exactly two
IAM-authenticated calls to the managed `WebSearch` Gateway connector for every
delegation: an unrestricted pass and a trusted-domain pass. Gateway-enforced
denylisted domains never become envelope output; duplicate URLs are surfaced
once as `trusted`.

With `scope.findings`, the final artifact contains linked `citations[]`.
Without findings, it contains `context_snippets[]` only. Both arrays never
coexist. The policy is [evidence-reputation.yaml](../../docs/evidence-reputation.yaml).

## Local Development

```bash
uv sync
uv run python main.py
```

The agent starts on port 9000.

## Deploy

```bash
agentcore deploy
```
