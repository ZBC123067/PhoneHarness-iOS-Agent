# ADR-048: Apple Maps Legacy Link Is the First Native Execution Adapter

Status: Accepted and implemented in TEST-42.1.

## Decision

Use a constrained `MapLinkAdapter` for a single public-destination Apple Maps
legacy link. It delegates the actual `open_url` call to the pre-existing
`PlanExecutor`; it has no direct MCP transport access and does not expose the
URL in its public result.

The adapter is used only after Capability Catalog evaluation, Solution and
Intelligence Orchestration recommendations, existing Planner selection, and
existing Risk Controller approval. The existing Verifier confirms Maps became
frontmost from a fresh read-only observation.

## Why This Adapter

- It is a documented iOS 17-compatible execution method.
- It is narrower and more stable than coordinate replay.
- It validates the native-adapter boundary before Shortcut/App Intent/API work.
- It preserves executor-only MCP hardening and verifier ownership.

## Rejected Alternatives

### Call `open_url` directly from the adapter

Rejected: bypasses the Executor and violates TEST-40.0 hardening.

### Declare a completed Maps navigation after link dispatch

Rejected: dispatch and a foreground Maps observation do not prove routing,
arrival, or user completion.

### Use Unified Maps URLs

Rejected: target device is iOS 17.0; Apple's Unified Maps URL API requires a
newer platform.

### Make a generic Shortcut or App Intent adapter first

Rejected: neither has an audited device invocation contract in PhoneHarness.
App Intents are inbound declarations owned by the application exposing them,
not arbitrary cross-app procedures.

## Consequences

TEST-42.1 can prove a real, bounded native dispatch path. It cannot claim
general application control or make the Maps method active without a separate
evidence/lifecycle decision. It does not alter RootHide, ElleKit, Bootstrap,
packages, sources, or the iPhone configuration.

## References

- [Apple Map Links](https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/MapLinks/MapLinks.html)
- [Apple App Intents](https://developer.apple.com/documentation/appintents)
- [Apple Unified Maps URLs](https://developer.apple.com/documentation/mapkit/unified-map-urls)
