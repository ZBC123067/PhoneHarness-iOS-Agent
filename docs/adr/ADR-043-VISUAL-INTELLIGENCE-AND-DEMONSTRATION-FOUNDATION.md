# ADR-043: Visual Intelligence And Demonstration Foundation

- Status: Accepted, TEST-40.1 semantic foundation implemented
- Date: 2026-08-23
- Scope: TEST-40.1 design

## Context

PhoneHarness needs future visual perception for screen and document assistance,
but it already has an AX-first Observation architecture and an executor-only
MCP action boundary. A screenshot-only or coordinate-replay design would
duplicate weaker information, leak private data, and weaken verification.

## Decision

1. Preserve the existing live-screen order: `AX -> Vision -> OCR -> VLM`.
2. Introduce a future Visual Capture System only through explicit, authorized
   ingress. Raw pixels are session-only and expire.
3. For image-only analysis, process OCR evidence before local vision inference
   without changing AX precedence for live screens.
4. Convert visual output to privacy-filtered semantic candidates only.
5. Treat all OCR and vision content as untrusted data, never as instructions.
6. Resolve domains generically with workspace hints and permission-scoped
   knowledge context. Low confidence or conflicts require confirmation.
7. Permit demonstration learning only in explicit Learn Mode. It creates a
   non-executing Procedure Candidate for TEST-31 and TEST-32 review, never a
   replayable trajectory or an executable script.
8. Keep all actions on the existing path: Planner -> Risk Controller ->
   PlanExecutor -> MCP -> Observation -> Verifier.

## Consequences

### Positive

- AX retains authority when it is available.
- A visual model cannot directly operate the phone.
- Captured private material has no durable screenshot, OCR, geometry, or replay
  store in this architecture.
- The same domain resolver can later serve shipping, language learning,
  automotive, and unknown domains without domain hard-coding.
- Demonstrations can become reviewed capability candidates without uncontrolled
  learning.

### Costs

- Visual fallback will require a separately authorized adapter and a focused
  real-device gate.
- Semantic-only contracts intentionally limit debugging detail; redacted trace
  events and session IDs must be used instead.
- Learn Mode requires explicit interaction and cannot learn silently from task
  history.

## Rejected Alternatives

1. Screenshot-first computer-use with coordinate actions: rejected because it
   conflicts with AX-first observation, privacy, reliability, and Executor-only
   MCP authority.
2. Persisted screenshot/OCR/embedding memory: rejected because it violates
   knowledge, memory, and experience minimization boundaries.
3. Automatic script creation from ordinary action history: rejected because it
   bypasses teaching consent, validation, and TEST-32 graduation.
4. Direct Apple Vision or VLM execution: rejected because perception cannot
   bypass Planner, Risk Controller, Executor, or Verifier.

## Compatibility

The TEST-40.1 foundation does not modify TEST-11 through TEST-40.0 module
boundaries, RootHide, Bootstrap, iOS code, packages, or the observation router.
It requires no migration. It adds only Mac-side semantic contracts with no
MCP/action authority.

## Validation State

The approved foundation has focused static and full offline regression evidence.
Its focused real-device gate consumed one existing AX-only `describe_screen`
observation through temporary USB forwarding, discarded the raw observation,
and produced `NEEDS_CONFIRMATION` for an ambiguous graph. No device action,
screenshot capture, OCR, or visual persistence occurred.

Visual Capture System ingress, Apple Vision OCR, local vision/VLM models,
image-only analysis, demonstration Learn Mode, procedure candidates, and all
visual action or UI features remain deferred.
