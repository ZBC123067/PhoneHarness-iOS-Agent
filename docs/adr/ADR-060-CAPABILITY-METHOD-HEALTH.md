# ADR-060: Capability Method Health Evidence

## Status

Accepted and implemented for TEST-47.

## Context

TEST-40.3 introduced `CapabilityMethodRegistry` as the declarative catalog of
ways to fulfil a capability. TEST-41 consumes its recommendation as advisory
input before the existing Planner, Risk Controller, Executor, and Verifier
boundaries. Method selection previously used declared method reliability,
verification, latency, and static aggregate evidence only.

That contract had no bounded way to reflect later verified method health. A
second Router, Planner, Memory system, capability catalog, or Executor would
duplicate stable boundaries and create unsafe action paths.

## External Review

The following ideas were evaluated and adapted without importing a framework:

- [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/):
  capabilities should be legible, enforceable, and continuously validated.
- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools):
  tool metadata is declarative and human approval remains appropriate for
  sensitive operations.
- [AWS agent routing pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/workflow-for-routing.html):
  routing should use explicit capability criteria and retain modular boundaries.

No project is imported. The selected design is a small adaptation because the
existing Registry already owns method metadata and TEST-41 already consumes
its recommendation.

## Decision

Extend `CapabilityMethodRegistry` with an in-process, platform-specific
`CapabilityMethodHealth` aggregate. Each record retains only:

- capability and method identifiers/names;
- declared platform;
- compatibility state;
- verification status;
- success/failure counts and fixed failure-category counts;
- recovery count; and
- last validation timestamp.

The registry emits this health summary as advisory evidence. It does not
dispatch a method, create a plan, authorize a task, call MCP, call a model, or
modify method lifecycle. TEST-41 receives the improved method advisory through
its existing `recommend()` call and no new orchestration component is added.

## Selection Policy

Current scoring considers declared availability, observed compatibility,
success rate, verification quality, the existing high-risk gate, latency, and
aggregate recovery cost. Incompatible or latest-verification-failed methods
are blocked before scoring. Existing static evidence remains the baseline when
no TEST-47 health record exists.

The contract declares `privacy`, `energy`, and `user_preference` as future
scoring dimensions but does not persist or fabricate values for them. A later
approved policy layer may supply bounded values through existing identity,
consent, and orchestration boundaries.

## Privacy and Storage

Health records reject goals, user content, screenshots, OCR/AX data, URLs,
coordinates, tool/action parameters, raw MCP data, and replayable traces.
They are intentionally in-memory only in TEST-47. Cross-process durability is
not claimed and requires a separately approved integration with the existing
unified private storage writer.

## Consequences

Positive:

- Existing orchestration can prefer measured healthy methods.
- Failed or incompatible methods fail closed rather than automatically retry.
- Health evidence remains explainable and privacy-minimized.

Deferred:

- Persistent method health across host restarts.
- Privacy/energy/preference weighting values.
- Device-side method-health collection and live provider expansion.
