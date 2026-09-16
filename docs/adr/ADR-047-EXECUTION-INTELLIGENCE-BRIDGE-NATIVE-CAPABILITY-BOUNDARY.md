# ADR-047: Execution Intelligence Bridge Uses Native Capability Adapters

Status: Accepted for architecture; TEST-42.1 implementation is recorded in ADR-048.

## Context

PhoneHarness has advisory capability, Skill, Shortcut, App Intent, and
intelligence orchestration registries, but it intentionally has no general
native execution adapter. The runtime already enforces a critical boundary:
only `PlanExecutor` owns the action-capable MCP port. TEST-42 must provide a
route toward structured/native actions without weakening that boundary.

The iOS 17 target supports Apple Maps legacy map links. App Intents is an app's
own declaration mechanism for its own actions and system entry points; it is
not a generic interface for calling arbitrary third-party App Intents.

## Decision

1. Add a future Executor-owned Execution Intelligence Bridge with a common
   adapter contract and verifier-issued result states.
2. Use the term `native_capability_link` for OS-registered links. Do not call
   it an "Official Capability API" or imply privileged API access.
3. Start with a single iOS-17-compatible Apple Maps legacy link adapter through
   the existing Executor-owned `open_url` execution path. Its implementation
   and focused device evidence are recorded in ADR-048 and TEST-42.1.
4. Keep PhoneHarness App Intents as future inbound system entry points only.
5. Defer existing Shortcut invocation until an audited real adapter exists;
   defer Shortcut creation/import and official third-party APIs to later phases.
6. Treat native-method preference as a ranking preference after hard eligibility
   gates, not as a bypass or fixed selection order.

## Consequences

Positive:

- Structured links can be safer and more stable than UI simulation.
- The first device gate is small, auditable, and compatible with iOS 17.
- Existing Planner, Risk, Executor, Verifier, consent, and privacy authorities
  retain their roles.

Costs and constraints:

- TEST-42 cannot promise general application control.
- Dispatching a link is not evidence that a user completed navigation.
- Shortcut and third-party API support need explicit platform and credential
  reviews rather than registry-only assumptions.

## Rejected Alternatives

### Direct adapter access to MCP

Rejected because it bypasses `PlanExecutor` and breaks TEST-40 hardening.

### Treat App Intents as arbitrary cross-app remote procedures

Rejected because App Intents are declared and implemented by the app exposing
the action. PhoneHarness cannot assume another app has an invocable intent.

### Generic Shortcut creation and execution now

Rejected because no verified creation/invocation bridge, user approval flow, or
device validation exists yet.

### Vision-first execution

Rejected because AX-first and structured native methods remain more reliable
when they are genuinely available. Vision remains a future constrained
fallback, never a direct control path.

## Compatibility

- iOS 17.0: Apple Maps legacy Map Links are supported; unified Maps URLs from
  iOS 18.4 are explicitly excluded.
- RootHide + ElleKit: no change to Bootstrap, injection, packages, sources, or
  configuration is needed.
- Existing PASS modules: no runtime code or authority boundary is modified by
  this ADR.

## References

- [Apple App Intents](https://developer.apple.com/documentation/appintents)
- [Apple Map Links](https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/MapLinks/MapLinks.html)
- [Apple Unified Maps URLs](https://developer.apple.com/documentation/mapkit/unified-map-urls)
