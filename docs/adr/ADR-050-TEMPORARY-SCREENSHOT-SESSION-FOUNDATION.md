# ADR-050: Temporary Screenshot Session Foundation

## Decision

Adopt a bounded, explicit-consent, in-memory screenshot session as the only
new TEST-44.1 visual-data boundary. Reuse the existing `CapabilityCatalog` for
metadata, `PermissionDecision` for eligibility, `VisualSemanticCandidate` for
safe semantic output, and the established
`Planner -> Risk Controller -> Executor -> Verifier` route for any future
action.

Do not add a screenshot database, a second visual memory system, a direct
visual-agent executor, or a device capture adapter in this phase.

## Context

PhoneHarness needs a future visual entry point without turning screenshots,
OCR, layout boxes, or user content into persistent agent memory. A capture
path or visual model that can directly issue actions would also violate the
existing AX-first observation and Executor-only action boundaries.

Apple Vision is an appropriate future local OCR candidate: its documented text
recognition runs on device, but it produces raw text observations and geometry.
Those values must remain session-private and cannot be used as durable
PhoneHarness state or action parameters. Apple also documents that Chinese
language correction and custom words are unsupported, so that behavior cannot
be assumed for the target's Chinese-first use cases.

## Alternatives Considered

### Persist screenshots with a semantic index

Rejected. It expands sensitive-data retention, adds ownership/consent,
forgetting, encryption, synchronization, and storage-recovery obligations, and
is unnecessary for a short-lived visual understanding request.

### Let Vision/OCR emit device actions directly

Rejected. This would bypass Planner, Risk Controller, Executor, Verifier, and
TEST-40 redacted trace requirements. Geometry is transient visual evidence,
not a replayable automation contract.

### Add an independent screenshot capability registry

Rejected. TEST-26/40.3 already own capability metadata and lifecycle. A
declarative `DISCOVERED` candidate is sufficient until an actual adapter is
audited and verified.

### Import a GUI-agent framework

Rejected. Screenshot-first GUI frameworks commonly couple pixel grounding with
coordinate actions. They conflict with PhoneHarness's AX-first observation,
privacy boundary, and Executor-only MCP boundary. Their evaluation ideas can be
revisited after a bounded local OCR adapter exists.

## Consequences

### Positive

- A future capture/OCR adapter has a small, testable and revocable privacy
  boundary.
- No visual payload becomes Knowledge, Memory, Experience, Context, State, or
  execution replay data.
- Low-confidence results are explicit and non-executable.
- Existing Planner/Risk/Executor/Verifier interfaces remain the only action
  route.

### Trade-offs

- There is no usable end-user screenshot feature in TEST-44.1.
- Closing a session clears PhoneHarness-owned references, but Python cannot
  promise complete sanitization of all external immutable-object memory.
- Apple Vision/OCR quality, Chinese handling, performance, and iOS 17 device
  behavior remain unverified until TEST-44.2.

## Compatibility

- iOS 17.0: no device API is invoked in TEST-44.1. Future Vision use requires
  a dedicated iOS 17 compatibility and device gate.
- RootHide + ElleKit: unaffected; the implementation is Mac-side Python and
  makes no package, bootstrap, tweak, source, or system configuration change.
- Existing PASS history: no prior TEST module is modified. Regression remains
  offline and confirms current unit contracts only.

## Validation Classification

- `STATIC_PASS`: focused 8/8 session-contract tests plus syntax compilation.
- `REGRESSION_PASS`: all 37 current offline unit suites.
- `DEVICE_PASS`: `N/A`, because no real capture/OCR/action behavior exists.
- `FUNCTIONAL_FAILURE`: none observed.
- `ENVIRONMENT_ISSUE`: none observed.
