# ADR-040: Continuous External Research Methodology

## Status

Accepted on 2026-08-22.

## Context

PhoneHarness is a privacy-governed Personal AI Operating System. Major runtime
changes need current external research without allowing external projects to
silently replace tested architecture.

## Decision

Each major proposal uses this sequence:

```
Research -> Technical Evaluation -> ADR -> Human Approval -> Implementation
```

Evaluation records source, license, activity, reusable part, required
modification, iOS 17 compatibility, RootHide and ElleKit compatibility, privacy
and security impact, migration cost, and effect on existing PASS evidence.

## Consequences

- Mature ideas may be adapted without importing heavyweight frameworks.
- A materially better solution requires an ACP before replacement.
- Existing device evidence is retained unless a replacement requires a new gate.
- External research cannot create device actions or change system configuration.
