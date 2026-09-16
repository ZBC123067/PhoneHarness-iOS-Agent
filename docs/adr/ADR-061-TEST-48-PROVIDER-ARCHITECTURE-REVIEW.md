# ADR-061: TEST-48 Provider Architecture Review

**Status:** Accepted - defer Frida runtime observation; no proof of concept

**Date:** 2026-08-26

## Context

PhoneHarness already has a privacy-minimized, read-only observation boundary:

```text
AX -> Vision -> OCR -> VLM (future)
```

Actions remain outside that boundary. The only action-capable MCP transport is
private to `PlanExecutor`; Planner, Knowledge, Memory, Experience, and
observation providers cannot call it. TEST-48 evaluates whether another
provider should be added without duplicating the existing Planner, Router,
Memory, Skill Registry, or Executor.

## Research Record

| Candidate | Reusable finding | License / compatibility finding | Decision |
| --- | --- | --- | --- |
| AX | Structured semantic screen state is already the primary, least-privileged PhoneHarness observation surface. | Existing project contract; no additional dependency. | Retain primary provider. |
| Vision / OCR | Apple Vision provides on-device text-recognition request APIs; PhoneHarness already reduces visual results to a redacted semantic contract. | Apple platform API; existing local visual implementation is the fallback. | Retain fallback; improve only through existing visual gates. |
| App Intents / Shortcuts | App Intents expose an app's declared actions to system entry points. They are execution/integration candidates, not generic observation of unrelated apps. | Apple platform API; each future adapter needs its own capability and device evidence. | Not an observation-provider POC. |
| MCP / Helper | The current read-only observation and private Executor action-port split is already the correct transport boundary. | Existing project contract. | Retain; do not add it to an untyped provider list. |
| Local AI | A local model can later be an advisory interpretation source, but has no demonstrated observation gap to solve in this stage. | Model/runtime qualification remains separate work. | Research only. |
| First-party network data | A service-owned structured API can be lower-risk than UI observation, but generic network inspection conflicts with ownership, TLS, and privacy boundaries. | Requires a separate per-service consent and API ADR. | Reject as a generic provider. |
| Frida runtime observation | Frida can instrument jailbroken iOS processes and attach to a running process, which can reveal in-process state unavailable to public UI layers. | Frida's main repository uses wxWindows Library Licence 3.1. RootHide + ElleKit compatibility and maintenance burden are not evidenced here. | Defer; no POC. |

Primary references: [Frida iOS](https://frida.re/docs/ios/),
[Frida source license](https://github.com/frida/frida/blob/main/COPYING),
[Apple Vision text recognition](https://developer.apple.com/documentation/vision/recognizetextrequest),
[Apple App Intents](https://developer.apple.com/documentation/appintents),
[MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools),
and [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/).

## Observation Gap Analysis

The current repository has no evidence-backed observation gap requiring
in-process runtime instrumentation. AX provides structured semantic state;
Vision and OCR are bounded fallbacks when AX is insufficient. The current
project has not identified a specific user goal, selected test app, or
Verifier condition where all of those sources are insufficient and a narrow
runtime value would materially improve success or recovery.

Adding Frida before that evidence would add a privileged injection surface,
an attach/detach lifecycle, per-app allowlisting, version fragility, and
private runtime-data exposure without a measurable benefit. It would also
require device preparation that is outside TEST-48's approved scope.

## Boundary Audit

The audit confirmed:

- `ObservationProviderRouter` accepts only `AX`, `Vision`, `OCR`, and `VLM`,
  in that fixed order.
- Every observation provider receives a read-only callable, not an MCP client
  or Executor port.
- `MCPClient.call_tool` is read-only; the action-capable transport is private
  to `PlanExecutor`.
- Existing App Intent and Shortcut registries are metadata-only declarations;
  they do not form an observation provider or bypass execution controls.
- No Frida runtime provider, attachment code, or injected device component is
  present in `phoneharness_agent.py`.

## Decision

**Decision: DEFER FridaRuntimeObservationProvider.**

TEST-48 changes no runtime provider order, device package, iOS configuration,
or provider interface. It authorizes neither a Frida installation nor a
device POC. Existing AX-first observation remains the required default.

A future Frida ADR and isolated POC are permitted only after all of the
following are documented:

1. One concrete, user-owned app observation gap that AX and Vision/OCR cannot
   meet.
2. A read-only, reversible observation question whose result improves a
   named Verifier or recovery decision.
3. One app allowlist and one runtime event/value allowlist; no broad tracing.
4. A privacy contract that reduces raw runtime values immediately and stores
   no private content, screenshots, coordinates, or replay data.
5. Explicit compatibility and maintenance evidence on the target iPhone 15
   Pro / iOS 17.0 / RootHide + ElleKit environment.
6. Separate approval for device preparation and a focused device gate.

## Consequences

### Positive

- The least-privileged AX-first architecture remains stable.
- No new injection, process-control, or data-persistence surface is added.
- Existing TEST-11 through TEST-47 contracts remain unchanged.

### Deferred

- Runtime-only state inspection.
- Frida attach/detach, compatibility, performance, and privacy evidence.
- Any claimed RootHide + ElleKit support for Frida.

### Rejected for This Stage

- Treating App Intents, Shortcuts, MCP, AX, Vision, and Frida as one generic
  provider type.
- Generic network interception.
- Production Frida integration or an unscoped device POC.

## Required Answers

| Question | TEST-48 answer |
| --- | --- |
| What gap exists? | None has been evidenced. |
| Can AX handle it? | AX remains the default for structured visible UI state. |
| Can Vision/OCR handle it? | They remain bounded fallbacks for visible state. |
| Can a native API handle it? | App Intents/Shortcuts can be future execution channels, not generic observation. |
| What unique benefit would Frida add? | Potential read-only in-process state, if a future named gap proves it necessary. |
| What privilege does it require? | A high-privilege process instrumentation/injection surface. |
| What privacy/security risk follows? | Runtime values can contain private application state; broad tracing is unacceptable. |
| What version risk follows? | iOS, app, jailbreak, and injected-runtime lifecycle compatibility require per-target evidence. |
| Does it improve Verifier/recovery? | Not yet demonstrated. |
| Is the benefit worth the cost now? | No. Defer until the evidence threshold above is met. |

## POC Decision

**No TEST-48 POC is approved.** Therefore no device behavior changed and no
new device evidence is required or claimed.
