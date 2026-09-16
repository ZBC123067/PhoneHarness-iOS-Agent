# ADR-046: Intelligence Orchestration Reuses Existing Runtime Boundaries

## Status

Implemented and validated for TEST-41.

## Context

PhoneHarness has independent modules for dynamic planning, tool selection,
Skills, permission and consent resolution, risk control, execution,
verification, capability intelligence, solution evaluation, adaptive
intelligence routing, human teaching, and experience learning. A new
Personal AI Operating System orchestration layer is needed to make their
advisory relationship clear without duplicating their authority.

## Decision

Add a stateless `IntelligenceOrchestrationLayer` on the Mac host. It accepts
only sanitized intent and declarative metadata, then returns a safe,
explainable recommendation:

- task classification;
- capability and solution recommendation references;
- advisory governed Skill candidates;
- advisory execution-method recommendation;
- intelligence source recommendation using the existing
  `AdaptiveIntelligenceRouter`;
- cloud approval metadata when cloud escalation is a candidate.

It is explicitly not authoritative for final planning, Skill selection,
permissions, risk, action execution, verification, persistence, or learning.

## Constraints

- The existing `PermissionResolutionEngine` remains the source of truth for
  consent and ownership. TEST-41 consumes only its decision.
- The existing `SkillRegistry.select` remains the only final runtime Skill
  selector. TEST-41 never calls it.
- The existing Capability Method Registry provides declarative method advice;
  TEST-41 expands its method vocabulary with `official_api` but does not
  implement an API client.
- The existing `AdaptiveIntelligenceRouter` remains the only adaptive source
  router. TEST-41 maps richer profile metadata into its established source
  categories.
- Executor-only MCP access remains unchanged.

## Alternatives Considered

### RouteLLM

RouteLLM is Apache-2.0 and provides evidence-driven weak/strong model routing.
It is not adopted because it has no governed capability, consent, verifier, or
iOS-device boundary. Its routing-evaluation principle is adopted.

### LiteLLM

LiteLLM is a broad provider gateway and routing layer. It is deferred because
PhoneHarness currently has no live model provider integration. Adding it now
would create a dependency and operational surface without any executable use.

### OpenAI Agents SDK Human-in-the-Loop

The SDK's pause/approve/resume model is a useful reference. A local approval
contract is adopted instead of the SDK because TEST-41 must remain provider
neutral, no-model-call, and compatible with existing task state handling.

## Consequences

Positive:

- Native interfaces can be preferred over UI automation when declared and
  verified.
- Cloud escalation becomes explicit, privacy-aware, and auditable before any
  provider is integrated.
- Existing PASS module authorities remain intact.

Negative:

- TEST-41 is advisory and intentionally cannot complete a device action.
- Live cost, latency, provider health, and model quality require a future
  Model Gateway and observed provider evaluations.

## Compatibility

The implementation is Mac-hosted Python and declares no iOS, RootHide,
ElleKit, Bootstrap, package, or device configuration change. It is compatible
with the iPhone 15 Pro / iOS 17.0 environment because it has no device-side
runtime behavior.
