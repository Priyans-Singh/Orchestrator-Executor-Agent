# ADR 003: Permit adaptive schema discovery without boundary expansion

**Status:** Accepted

## Context

The initial Sheet does not have a guaranteed metric schema. The system must
discover useful business fields while preserving a controlled data boundary.

## Decision

Allow the diagnostic analyst to inspect and map compatible headers and types
within the approved gateway scope. It may map a renamed field to a
pre-approved semantic field, record that mapping, and lower confidence where
appropriate. It may not use a newly discovered column or tab merely because it
appears relevant.

When evidence is insufficient, the system asks targeted questions. It may run a
best-effort analysis only after the user explicitly confirms it.

## Consequences

- The agent can adapt to benign schema drift.
- The data contract remains the access authority.
- Discovery and uncertainty need explicit evaluation coverage.
