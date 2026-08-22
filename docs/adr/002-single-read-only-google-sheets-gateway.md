# ADR 002: Enforce all Google Sheets access through one gateway

**Status:** Accepted

## Context

The MVP uses real business data from Google Sheets and must demonstrate
least-privilege access for multiple agents.

## Decision

Use AgentCore Gateway as the only read-only path to Google Sheets. The gateway
uses the user's narrowly scoped personal OAuth refresh token. No agent receives
Google credentials or direct Sheets access.

The gateway policy is version controlled. It limits the spreadsheet scope,
approved tabs, semantic fields, operations, and query limits. It rejects
requests outside that policy before contacting Google.

## Consequences

- Access decisions are auditable in one place.
- OAuth secrets must be stored and rotated outside application code.
- A future multi-user version will require a separate identity and authorization
  design.
