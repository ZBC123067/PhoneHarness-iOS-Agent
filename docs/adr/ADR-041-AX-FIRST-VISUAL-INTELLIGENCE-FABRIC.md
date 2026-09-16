# ADR-041: AX-first Visual Intelligence Fabric

## Status

Accepted on 2026-08-22. Design only.

## Decision

PhoneHarness keeps AX as the primary source of semantic UI state. Future visual
understanding follows this confidence hierarchy:

```
AX -> OCR-grounded understanding -> vision understanding -> GUI grounding policy
```

The existing TEST-21/22 provider order remains intact until a separately tested
compatibility decision changes it. GUI grounding is a policy stage that returns
only an uncertainty-aware candidate; it is not an executor and cannot call MCP.

## Privacy Boundary

Visual processing is session-authorized and ephemeral by default. Durable
storage rejects screenshot bytes, OCR text, coordinates, AX dumps, and action
replay parameters. Approved summaries remain subject to Knowledge, Experience,
Consent, and lifecycle rules.

## Alternatives Rejected

- Screenshot-only automation: loses accessible structure and creates privacy
  and grounding risk.
- Coordinate-replay learning: fragile across screen state and disallowed by the
  capability graduation boundary.
- Direct vision-to-device control: bypasses Planner, Risk, Executor, and
  Verifier.
