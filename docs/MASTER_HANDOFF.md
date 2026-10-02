# PhoneHarness Master Handoff

> **P21-P24 GOVERNANCE NOTE (2026-09-30):** S4-M6 Process / Service is the first
> module operating under the mandatory permanent `P21 — AI-Native System
> Unity` freeze gate. From S4-M6 onward, every A0 audit must include an
> AI-Native Integration Audit and every Final Closeout/Freeze must pass the
> P21 AI-native gate (`AI_NATIVE_INTEGRATION = PASS`, no intelligence
> islands, no feature-specific AI/world/memory runtimes). Authoritative
> statement: canonical roadmap, "P21 — AI-Native System Unity" and
> "P21 Freeze Gate".
> P22 makes governance agent-independent; P23 binds one shared semantic
> context fabric without granting authority; P24 defines perceptually
> real-time interaction through measurable device evidence. The P0 daily AI
> learning trinity is Personal Translator, Smart Screenshot Studio, and Live
> Media Interpreter. One Settings Registry serves multiple projections.


LOCAL_AI_TAKEOVER_READY: YES

## Canonical Roadmap And Current Status

The single live roadmap is:

`docs/roadmap/PHONEHARNESS_CANONICAL_ROADMAP.md`

Current stage state is `STAGE_2_STATUS = FROZEN_PROVEN` and
`STAGE_3_STATUS = FROZEN_PROVEN`. `S4-M0` through `S4-M5` are
`FROZEN_PROVEN`. The current module is `S4-M6 Process / Service`.
`CURRENT_COMPLETED = S4-M6-A3-R2` and
`CURRENT_NEXT = S4-M6-A3-R3 (PLANNED / NOT_EXECUTED)`.
The A3-R3 gate is not a completed or passing result.

The S4-M5 frozen source incident was recovered byte-exactly. The repository
root source matches its historical SHA256 and the final manifest is 8/8. A
durable recovery-only copy is retained under
`diagnostics/recovery/s4-m5-incident-2026-09/`; it is not production source
and does not redefine the historical freeze.

The dated status, Git, device, TEST-52, and next-action sections below are
retained as `HISTORICAL_REFERENCE`. They remain evidence for their recorded
time and scope, but they are not the live project stage or future roadmap.

## Current Source of Truth

Repository: this target repository checkout.
Golden baseline: the separately maintained PhoneHarness baseline (read-only).

This handoff preserves detailed historical operational context. It supplements
the canonical roadmap and the historical test and ADR evidence under `docs/`.

Repository evidence, current code, current Git state, and fresh test/device
evidence are authoritative. Conversation history and model assumptions are not.

## Project Purpose And Target

PhoneHarness is a personal iPhone AI Agent / Personal AI Operating System. Its
intended closed loop is to observe, understand context, plan, select governed
capabilities and Skills, execute safely, verify reality, retry or replan,
recover after interruption, and maintain privacy-safe contextual continuity.
Future entry and experience surfaces include Siri, Shortcuts, App Intents,
Action Button, a minimal app UI, Live Activities, and governed scheduling.

Target device:

- iPhone 15 Pro (`iPhone16,1`)
- iOS 17.0
- RootHide + ElleKit

## Historical Git Snapshot (2026-09-04)

Codex current post-governance-fix through Track C1 Host/build-only snapshot,
verified 2026-09-04:

- HEAD: `54e98829bb92a8b0f22a4970bd81830b4e376799`
- State: detached HEAD
- Modified tracked files: 23
- Untracked entries reported by `git status --porcelain=v1`: 150
- Staged files: 0

This is distinct from the ZCode historical snapshot (22 modified / 142
untracked entries) and the original takeover baseline (17 / 137). Historical
figures remain unchanged in `_zcode_workspace/reports/ZCODE_FINAL_HANDOFF.md`;
they are not the expected current worktree counts.

The dirty and untracked files are active project work. Do not clean, reset,
restore, checkout over, stash, or delete them merely to simplify takeover.

## Current Core Architecture

```text
Goal
-> Context
-> Dynamic Planner
-> DynamicPlan
-> Plan Validator
-> TaskCoordinator
-> Risk Controller
-> Capability Binding
-> capability-specific Adapter
-> PlanExecutor
-> TEST-45 Action Obligation Ledger
-> Observation
-> Verifier
-> Retry / Replan
-> Recovery
-> Durability
-> Retention
-> Task Lifecycle
```

Authority remains separated:

- Planner proposes.
- TaskCoordinator orchestrates.
- Risk Controller authorizes and classifies risk.
- Capability Binding selects a trusted registered route.
- Adapter performs capability-specific translation only.
- PlanExecutor executes governed work.
- Ledger records the governed action lifecycle.
- Observation collects reality without granting authority.
- Verifier alone decides semantic success.
- Recovery reconstructs and revalidates without replay.
- Task lifecycle authority derives task-level terminal state.

No layer silently inherits another layer's authority.

## Historical Stage Snapshot (Pre-Stage-2 Roadmap)

Latest completed functional gate: `TEST-59 HOST_PASS`.

The Agent Runtime Foundation from TEST-53 through TEST-59 is complete on the
host. Recovery and durability work is closed unless a concrete new blocker is
demonstrated. TEST-60 is planned but has not started.

- TEST-59: host implementation complete for Governed Task Lifecycle / Terminal
  Acknowledgement V1. The existing TaskCoordinator now derives terminal task
  candidates only from TEST-45 Ledger, Verifier, current revision, recovery,
  and TEST-58 reconciliation evidence. Explicit acknowledgement is separate
  from Risk confirmation and is required before a TEST-59-managed task becomes
  retention eligible. Unknown outcomes, evidence conflicts, pending
  verification, and active replans cannot be cleaned. Evidence: static 2/2,
  focused 12/12, related regression 183/183 methods, lifecycle E2E 1/1, and
  offline regression 59/59. `DEVICE_RESULT=NOT_RUN`, `device_action_count=0`.
  TEST-49/50 route behavior is unchanged and TEST-51/52 remains fail closed.
  See `docs/TEST-59-GOVERNED-TASK-LIFECYCLE-TERMINAL-ACKNOWLEDGEMENT.md`
  and ADR-073.
- TEST-58: host implementation complete for Recovery Retention / Store-Ledger
  Consistency V1. It adds explicit task-scoped Ledger-first reconciliation and
  an atomic compare-and-delete path inside the existing coordinator store.
  Terminal VERIFIED, terminal failure, cancellation, and safely superseded
  revisions may release checkpoint/lease metadata while the bounded TEST-45
  audit remains. Conflicts, orphan evidence, active ownership, and unknown
  external outcomes remain retained and non-replayable. Evidence: static 2/2,
  focused 15/15, related recovery regression 66/66, process E2E 1/1, and
  offline regression 58/58. `DEVICE_RESULT=NOT_RUN`, `device_action_count=0`.
  TEST-49/50 route behavior is unchanged and TEST-51/52 remains fail closed.
  See `docs/TEST-58-RECOVERY-RETENTION-STORE-LEDGER-CONSISTENCY.md` and ADR-072.
- TEST-57: host implementation complete for Process Durability / Recovery
  Ownership & Fault Injection V1. It extends the existing TEST-46/56
  coordinator persistence with optional bounded recovery leases and monotonic
  fencing tokens. Real independent processes passed natural exit, SIGTERM,
  SIGKILL, simultaneous recovery, stale-owner transfer, old-owner fencing,
  unknown-outcome no-replay, durable VERIFIED no-duplicate, and persistence
  fault cases. Evidence: static 3/3, focused 15/15, related recovery regression
  117/117, and offline regression 57/57. `PROCESS_CRASH_DURABILITY=HOST_PASS`,
  `PHYSICAL_POWER_LOSS_DURABILITY=NOT_TESTED`, `DEVICE_RESULT=NOT_RUN`, and
  `device_action_count=0`. Existing TEST-49/50 behavior is unchanged;
  TEST-51/52 remains fail closed. See
  `docs/TEST-57-PROCESS-DURABILITY-RECOVERY-OWNERSHIP.md` and ADR-071.
- TEST-56: host implementation complete for Restart-Safe Dynamic Plan Recovery /
  Governed Resume V1. It extends the existing TEST-46 coordinator store with
  optional typed checkpoints, reconstructs runtime state across a real
  serialization/object-destruction boundary, revalidates current Plan revision,
  Capability/Skill/Method Health, Risk, Ledger, and Verifier evidence, then
  rebinds only fresh process-local typed capability inputs. Verified work is not
  duplicated; dispatched/observing interruption becomes
  `EXECUTION_OUTCOME_UNKNOWN` with no blind retry. Evidence: static 3/3,
  focused 18/18, host restart E2E 3/3, related regression 141/141, and offline
  regression 56/56. `DEVICE_RESULT=NOT_RUN`, `device_action_count=0`. Existing
  TEST-49/50 behavior is unchanged; TEST-51/52 remains fail closed. See
  `docs/TEST-56-RESTART-SAFE-DYNAMIC-PLAN-RECOVERY.md` and ADR-070.
- TEST-55: host implementation complete for Governed Capability Adapter
  Binding V1. TEST-54 compiled steps now bind through task/revision-scoped,
  one-time typed contracts to the existing read-only observation route,
  `MapLinkAdapter`, or installed-app binding, then enter the existing
  `PlanExecutor`, TEST-45 Ledger, Observation, and Verifier. Execution-time
  Risk, method, platform, permission, dependency, target freshness, and
  evidence correlation are rechecked. Evidence: static 2/2, focused 24/24,
  host E2E 3/3, related regression 127/127, and offline regression 55/55.
  `DEVICE_RESULT=NOT_RUN`, `device_action_count=0`. Existing TEST-49/50 route
  behavior is unchanged. See `docs/TEST-55-GOVERNED-CAPABILITY-ADAPTER-BINDING.md`
  and ADR-069.
- TEST-54: host implementation complete for Dynamic Plan Runtime Integration /
  Governed Task Coordination V1. The existing `TaskCoordinator` now admits
  deterministically compiled TEST-53 Plans, enforces explicit step/dependency
  state, calls the existing Risk Controller before its typed executor facade,
  requires Observation and Verifier evidence, supports bounded structured
  replanning, and rejects stale revisions. Evidence: static 2/2, focused
  23/23, related runtime 105/105, and offline regression 54/54.
  `DEVICE_RESULT=NOT_RUN`, `device_action_count=0`. See
  `docs/TEST-54-DYNAMIC-PLAN-RUNTIME-INTEGRATION.md` and ADR-068.
- TEST-53: host implementation complete for Dynamic Planner / Agent Brain V1.
  It extends the existing `DynamicPlanner` with privacy-minimized typed input,
  typed semantic Plans, deterministic validation, Capability/Skill/Method
  Health integration, verifier requirements, Risk-only handoff, and bounded
  structured replanning. Evidence: static 2/2, focused 27/27, related runtime
  105/105, and complete offline regression 53/53. `DEVICE_RESULT=NOT_RUN` and
  `device_action_count=0`. See `docs/TEST-53-DYNAMIC-PLANNER-AGENT-BRAIN-V1.md`
  and ADR-067.
- TEST-50: complete and `DEVICE_PASS`, limited to governed handoff of one
  explicit public destination to Apple Maps with fresh foreground observation.
- TEST-51: host modernization complete. It supersedes TEST-25 execution
  governance while preserving its historical evidence. Host evidence: static
  compilation 2/2, focused unit 18/18, integration 7/7, negative 25/25,
  security 12/12, regression 51/51, and synthetic host E2E pass.
- TEST-51 device action Gate: `BLOCKED`. No governed focus, input, or submit is
  authorized until a provider proves the complete TEST-52 same-leaf state
  contract (`device_action_count=0`).
- TEST-52: `NOT_PASS` with `AUTHORIZATION_RESULT=FAIL_CLOSED`. The final
  XCTest Observation Provider is independently `DEVICE_PASS` for a
  privacy-safe, read-only snapshot diagnostic, but it does not prove the
  authorization-grade editable, secure-false, visible, or Safari address-field
  identity required to authorize TEST-51.

## Historical Device Environment Snapshot (2026-08-28)

On 2026-08-28, the RootHide package
`1.2.2+ph1-12+roothide+debug-1+debug` was installed and its running identity
matched build `phb-702c778a809fa4d907342f1d`. The following environment checks
worked:

- USB device enumeration;
- SSH connectivity;
- iOS MCP service health on port 8090;
- USB forwarding to the MCP health endpoint.

This is environment readiness only, not a TEST-52 pass.

## TEST-52 Final XCTest Snapshot Provider Closure

The historical ph1-12 AX observation remains evidence of its own bridge and
field-authority failure. It sent no device or MCP action capable of changing
device state. The later B10 XCTest diagnostic independently completed on the
same device without actions.

- `semantic_field_count=54`
- `eligible_field_count=0`
- `direct_state_count=0`
- `unknown_state_count=270`
- provenance: `inferred=54`, `unavailable=324`
- result: `FAIL`

The B10 XCTest Provider built and ran one test with zero failures. It acquired
one `fb_standardSnapshot`, structurally traversed it to depth 18 of a configured
maximum 50 without detected truncation, and made no action-endpoint call.
It directly observed type, enabled, `hasFocus`, existing WDA
`hasKeyboardFocus` API readability, and same-snapshot structure. It did not
directly prove `editable=true`, `secure=false`, authorization-grade visibility,
or Safari address/search-field identity. The observed `HAS_FOCUS` node and
semantic-field node were structurally `UNRELATED`.

This closes the current provider exploration: `XCTEST_OBSERVATION_PROVIDER`
is `DEVICE_PASS`, while TEST-52 itself remains `NOT_PASS` and TEST-51 remains
`BLOCKED`. The result is not an environment, WDA, Xcode, or iOS 17 failure.
The same device/Mac/Xcode control established
`ROOT_HIDE_AMFI_CAUSAL_CONTROL=PASS`: active RootHide/Bootstrap caused the
CoreDevice/XCTest AMFI launch-constraint behavior; a normal non-Bootstrap
reboot allowed CoreDevice, WDA, XCTest, and `fb_standardSnapshot` to run.

Do not patch AMFI or launchd on the main phone. No repository source-of-truth
evidence establishes Dopamine as a verified PhoneHarness solution; it must not
be promoted from unverified candidate status without a separate applicable
gate.

## Frozen Security And Recovery Invariants

- `TextField` does not prove `editable=true`.
- A non-secure element type does not prove `secure=false`.
- Derived visibility is not authorization-grade visibility.
- Cross-node focus is not same-leaf semantic authorization.
- XCTest Observation Provider `DEVICE_PASS` does not authorize arbitrary
  `INPUT_TEXT` or `SUBMIT`.
- Memory, Context, Skill, Planner, Siri, Shortcut, App Intent, Scheduler, and
  UI may not bypass TEST-52.
- Checkpoint is not authorization, current observation, or execution truth.
- Unknown execution outcome is never blindly replayed.
- Old confirmation does not authorize future execution.
- Stale observations cannot authorize resumed execution.
- Physical power-loss durability remains `NOT_TESTED`.

Knowledge, Memory, Experience, Active Context, Reference Resolver, Planner,
State, and Execution remain conceptually separate. Do not create a generic
second Memory, Context, Planner, Router, Skill Registry, Capability Registry,
Executor, Ledger, or Verifier.

## Historical Next Action Snapshot

The Project-Wide Foundation Stabilization Audit host-convergence work is
complete through P1-6. P1-2/P1-3/P1-4 remain host-verified source corrections:
Content-Disposition filenames are header-safe, runtime filesystem instructions
no longer promise an unavailable mcp-root fallback, and command timeouts kill
an isolated process group. P1-5 now documents one canonical governed dynamic
task route and three still-reachable compatibility routes without deleting or
creating a second subsystem. P1-6 adds short critical-section locking to the
shared mutable binding, authorization-consumption, coordinator, semantic-task,
input-binding, and method-health state. No lock is held across provider,
executor, observation, or verifier work.

Evidence: target SDK syntax 2/2; P1-2/P1-3/P1-4 focused Host tests 12/12;
P1-5/P1-6 convergence tests 3/3; affected coordinator tests 10/10; and
offline regression 66/66. No package was deployed and no device regression
ran for this host-only batch.

TEST-52 Track A Evidence Correctness Hardening is now HOST_PASS (2026-09-03):
secure type inference is DERIVED, invalid AX states cannot become direct
booleans, raw same-leaf flags do not authorize, bundle/context fingerprints use
actual keys and reject contradictions, and receipt freshness is explicitly
Host-derived with device generation unavailable. Diagnostic success validates
property types; role reads no longer count as secure-property availability.
Evidence: new 31/31 methods (including seven native source-only assertions),
combined focused 208/208 methods across 11 suites, full Host 67/67 suites.
No target compile/build/deploy or device action occurred at that Host-only
hardening stage. TEST-51 remains Host
PASS / Device BLOCKED; TEST-52 remains NOT_PASS / FAIL_CLOSED. Input methods
remain CANDIDATE; WDA remains CANDIDATE_ENV_BLOCKED; Phase 6 remains BLOCKED.

The owner has manually installed/restarted diagnostic debug-9. Fresh authenticated
health, installed Build Identity `phb-2739dd553fa0730ff5b17ef6` and live
`test52_read_only` schema matched. An initial non-target page read returned 56
nodes in 441.07 ms and is retained as limited diagnostic evidence. The corrected
public automation test form then produced the applicable A-unfocused read: 29
nodes in 401.5 ms with `AVAILABLE`, no-bootstrap policy and `FAIL_CLOSED`
authorization. Across that correct form, semantic role/editable/secure/enabled/
focused/actionable evidence was UNAVAILABLE for all nodes; visibility was
DERIVED. Same-leaf identity and device generation remained unavailable; neither
field A identity nor focused=false was proven. Host receipt time is not snapshot
proof. See `evidence/device/test52-tracka-public-form-a-unfocused.json`.

`TRACK_A=INSUFFICIENT_FOR_CURRENT_AUTHORIZATION_CONTRACT`. The missing-evidence
stop rule was applied: on the correct form, B focused and secure focused are
NOT_TESTED; the initial page is not field-state evidence.
No more AX probing, default-route retries, WDA work, Phase 6 or TEST-60 is
authorized. At Track A closure the next step was the separately approved Track C
design review. The later approved C1 Host/build-only result is recorded below.
Evidence: `evidence/device/test52-tracka-debug9-a-unfocused.json` and
`docs/TEST-52-AX-SEMANTIC-FIELD-OBSERVABILITY.md`. No raw UI/value/rect data was
retained. Device fallback counters were not instrumented; retain the distinction
between the live route/build match and prior Host failure-path tests.
Device/MCP action counts and Executor invocation count are 0; temporary USB
forwarding was stopped. Method Health is unchanged: this is an observation gap,
not an execution-method failure. Production fallback defaults are unchanged.
TEST-52 remains NOT_PASS/FAIL_CLOSED; TEST-51 device BLOCKED; Phase 6 BLOCKED.

**Historical Track C1 update (2026-09-04): HOST_PASS / BUILD_PASS, NOT_DEPLOYED.**
The controlled native fixture and default-off, fixture-only ElleKit observer
are implemented under `diagnostics/test52-c1/`. A compile-time optional branch
reuses authenticated MCP get_ui_elements, strict kernel-peer/pinned IPC and the
existing evidence/Risk boundary. No direct input, new Executor or Risk relaxation.
35/35 initial C1 tests (9 static + 26 native/Host) and full Host 69/69 suites PASS.
App/observer/diagnostic MCP compiled arm64 + arm64e; root/root packages audited.
Native getter support is Host/build evidence only. UITextField editable,
visible/actionable, AX same-leaf and atomic device generation remain gaps.
See `docs/TEST-52-C1-CONTROLLED-NATIVE-OBSERVER.md` and
`evidence/host/test52-c1-package-evidence.json`. Next step is owner approval
before any installation/controlled read-only device gate. No automatic deploy.
TEST-52 NOT_PASS/FAIL_CLOSED; TEST-51 device BLOCKED; Phase 6 BLOCKED; actions 0.

**Historical C1 live/startup update (2026-09-04): BLOCKED; C1.1 HOST/BUILD PASS.
Fixture runtime identity is verified; runtime-pin MCP remains NOT_DEPLOYED.**
The original C1 packages were manually installed and resprung.
The fixture opened and its owner enabled observation, but the expected
fixture-only listener socket did not appear. No IPC capture, content read or
device action occurred. Source review identified a minimal likely startup race:
the Observer constructor could test the app bundle before UIKit initialization
and miss a pre-existing owner opt-in. C1.1 defers the bundle/symbol checks to the
main queue and calls `OwnerChanged()` after registering notifications. It keeps
default-off, fixture-only injection, authenticated IPC and every TEST-52
fail-closed boundary intact. C1.1 tests: 37/37; full Host 69/69; arm64/arm64e
build PASS. Its audited fixture-only package is
`diagnostics/test52-c1/packages/com.charles.phoneharness.test52.c1_0.1.0-c1-20260904-1+debug-audited_iphoneos-arm64e.deb`
(SHA-256 `50c9c5356767115c270958fd8a699591f3b123e5932bdf753fcae351900ed6e2`),
with 15 root/root, non-world-writable members and the original file set. It is
not deployed: its companion MCP C1.1 exact-pin package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.1+debug_iphoneos-arm64e.deb`
(SHA-256 `cf31dad9e2503c4d66a714b8f22e3cdbef7dbc4d498a0b9ec5e5a3d1f5ddc6f5`).
It derives and compiles both exact C1.1 Fixture CDHashes from the audited package
(arm64 `404b2bcd54581a808461f3f63a35c755e349cf98`; arm64e
`ebb0ec96edc161b775c6c58a048bb4d4d0ab302c`), contains neither prior C1 pin,
keeps kernel peer/path/PID-version checks, and has the debug-9 file set with only
the MCP dylib and Build Identity content changed. All archive members are
root/root and `mcp-root=4755`. Exact pin tests 5/5, C1 Host tests 37/37 and full
Host 69/69 PASS. This is a manual-install handoff, not a device claim: RootHide
appatch may re-sign the fixture at installation, so a future read-only runtime
CDHash comparison is mandatory and mismatch remains BLOCKED. Do not weaken the
pin or claim C1 device evidence. TEST-52 remains NOT_PASS/FAIL_CLOSED; TEST-51
device BLOCKED; Phase 6 BLOCKED; C1.1 device actions 0. The isolated C1.1 MCP
source tree has the same 51 files as the prior C1 tree; only generated
`PHC1FixturePin.h` differs.

**C1.1 runtime-CDHash refresh (2026-09-04): Fixture install/read-only identity
validation PASS; MCP installation and C1 capture remain NOT_RUN.** The manually
installed C1.1 Fixture is registered as `com.charles.phoneharness.test52.c1`
through authenticated MCP read-only `get_app_info`. Device-side read-only
inspection found the canonical executable `/Applications/PHC1Fixture.app/PHC1Fixture`
and RootHide mapping
`/var/containers/Bundle/Application/.jbroot-62887242FDD2F104/Applications/PHC1Fixture.app/PHC1Fixture`.
Its runtime SHA-256 is
`a9da919c89e12ff1192d2eca8dc89187711086b0d220866513ee1ac9ec93f89d` and the
active arm64e CDHash is `6d3451182910f07efcfc8b106a4edaa4427b7a09`. Both differ
from the fixture archive bytes/pins, and the live CodeDirectory reports a
TrollStore signing authority: runtime re-signing is proven; appatch attribution
is consistent with the RootHide installation path but was not independently
logged. The package-derived C1.1 MCP is therefore rejected and remains
uninstalled. A fresh exact runtime-pin MCP package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.2+runtime-pin+debug_iphoneos-arm64e.deb`
(SHA-256 `07ac51fcf03700fe288128c42098e9861b83026714efa949e2e62fb318593339`).
It accepts only that observed arm64e CDHash (duplicated only to retain the
fixed two-slot receiver ABI; no alternate hash is accepted), preserves exact
path, kernel peer, PID/version, and snapshot bundle checks, and has the same
debug-9 data file set with only the MCP dylib and Build Identity changed.
Archive audit: 38 root/root entries, no world-writable entries, `mcp-root=4755`.
Runtime negative tests 9/9, earlier exact-pin tests 5/5, C1 tests 37/37, and
full Host regression 69/69 PASS. TEST-52 remains NOT_PASS/FAIL_CLOSED; TEST-51
device BLOCKED; Phase 6 BLOCKED; this identity read and all build work performed
zero device actions. **Post-install verification:** the installed package reports
version `1.2.2+ph1-13+roothide+c1-1.2+runtime-pin+debug`; authenticated health
is HTTP 200 and unauthenticated health is HTTP 401. The installed MCP dylib has
a different whole-file SHA-256 after RootHide processing, but contains the exact
observed runtime pin and no package/prior pins. Its arm64 and arm64e `__TEXT`
code-and-constant sections compare byte-for-byte with the audited package; only
signing/loader metadata differs. With Observer OFF, the listener is absent before
and after one explicit C1 read-only request; that request returns
`UNAVAILABLE/BLOCKED`, carries no snapshot, and performs no mutation. Positive
IPC and every field observation remain NOT_RUN pending manual Observer enable.

Track A diagnostic build preparation subsequently produced local debug-8
package `com.witchan.ios-mcp_1.2.2+ph1-13+roothide+debug-8+debug-1+debug_iphoneos-arm64e.deb`
(build identity `phb-4b911a577487fcae83119cc9`, SHA-256
`d73c9afb20bc75920aad9b154606b46198578cec6f302fe1b7874c85e3401eca`).
It compiled/link-tested arm64 and arm64e and was repacked with
`dpkg-deb --root-owner-group` (`root/root`, `mcp-root` mode `4755`). It has
not been transferred, installed, or run on the iPhone: compact AX observation
may activate AXUIClient/VoiceOver bootstrap after a failed read, and that
artifact had no no-bootstrap request option. This historical
`BLOCKED_PRE_DEPLOY` condition was not a TEST-52 or device-method failure.
`device_action_count=0`.
Preserve debug-7/debug-5/debug-4/ph1-12 rollback packages. See
`docs/TEST-52-AX-SEMANTIC-FIELD-OBSERVABILITY.md`.

**C1.2 pre-listener activation diagnostic (2026-09-04): HOST/BUILD/PACKAGE
PASS; DEVICE PRE-LISTENER BLOCKED.** The live C1.1 Fixture switch was reported ON while the
fixture was foreground, but `observer.sock` remained absent. This is a
pre-listener observability blocker, not a peer-authentication, Risk, Executor,
or TEST-52 authorization result. The fixture-only C1.2 Observer adds a fixed,
atomic startup state file independent of the socket. It reports only fixed
constructor/main-queue/filter/export/enable/listener/socket errno states and no
fields, values, coordinates, screenshots, IPC payloads or control interface.
It does not change the exact peer pin, kernel credential checks, MCP response
contract, Risk, binding, Executor, Ledger or Verifier. Static archive review
confirms the existing bundle filter and exports, but live dylib load remains
unproven until an owner-approved C1.2 installation/read-only state check. C1.2
Host/native tests 40/40, runtime-pin tests 9/9, prior exact-pin tests 5/5, and
full Host 69/69 PASS. The final audited package is
`diagnostics/test52-c1/packages/com.charles.phoneharness.test52.c1_0.1.0-c1-20260904-2+startup-debug-audited-r3_iphoneos-arm64e.deb`
(SHA-256 `85ac4d2c72df185c63ea2f8146af96265f0c1adef9f713ae559ae0271388c29b`).
It preserves C1.1's 15 root/root, non-world-writable entries and full file set;
only `PHC1Observer.dylib` changes. The owner later installed C1.2 and resprung.
The runtime Fixture CDHash still exactly matched the MCP pin, but startup
breadcrumbs were absent with the Observer OFF, so live dylib load/constructor
entry remains NOT_PROVEN and the listener/IPC/field Gate was not run. TEST-52
stays NOT_PASS/FAIL_CLOSED; TEST-51 stays device BLOCKED; Phase 6 stays BLOCKED;
device actions 0. See
`docs/TEST-52-C1-CONTROLLED-NATIVE-OBSERVER.md` and
`evidence/host/test52-c1.2-startup-diagnostic-package.json`.

**C1.3 Injection Isolation Gate (2026-09-04): HOST/BUILD/PACKAGE PASS;
DEVICE GATE FAIL, device actions 0.** C1.2 cannot distinguish absent injection from the Observer's
own pre-listener path. C1.3 introduces a separate Fixture-filtered canary dylib
whose constructor only atomically writes fixed structural state
(`loaded`, pid, monotonic ticks and own image path). It has no UIKit/Foundation,
field access, preferences, socket, IPC, MCP, action path or Runtime authority.
Host/native canary tests 6/6, existing C1 tests 40/40 and full Host 69/69 PASS.
The audited root/root, non-world-writable two-file package is
`diagnostics/test52-c1-canary/packages/com.charles.phoneharness.test52.c1.canary_0.1.0-c1.3-20260904-2+canary-audited-r7_iphoneos-arm64e.deb`
(SHA-256 `cd42195c5ead01ef10f459f85301ce08d24168663000c3080c2e4e9e991d1453`).
The owner manually installed it, resprung, launched the Fixture and left the
Observer OFF. The canary state file remained absent, so this exact injection
path failed without exercising Observer, IPC, MCP, fields or device actions.
The remaining scope is filter matching, RootHide path translation, ElleKit
activation/preload, loader eligibility/signing or fixed-state persistence. It
does not pass TEST-52 or permit Phase 6. See
`docs/TEST-52-C1.3-INJECTION-ISOLATION.md` and
`evidence/host/test52-c1.3-injection-canary-package.json`.

**C1.4 Fixture Installation-Form Experiment (2026-09-04): HOST/BUILD/PACKAGE
PASS; MANUAL TROLLSTORE INSTALL NOT_RUN, device actions 0.** C1.3's failed
canary load left an unproven, high-probability installation-form hypothesis:
the `.deb`-installed `/Applications` Fixture may not be eligible for Bootstrap's
target-app injection list. C1.4 changes only the controlled Fixture's delivery
form to a Fixture-only TrollStore IPA. Its payload contains exactly
`Payload/PHC1Fixture.app/PHC1Fixture` and `Info.plist`; it contains no Observer,
Canary, MCP, IPC, action interface, or new mutation capability. Bundle ID,
controlled fields, default-off Observer ownership, and TEST-52 authorization
criteria are unchanged. The IPA is not device proof and must be installed only
manually. After a TrollStore install, the existing MCP runtime CDHash pin
`6d3451182910f07efcfc8b106a4edaa4427b7a09` is **UNVERIFIED** until the installed
executable's canonical path, SHA256, and arm64e CDHash are freshly read. Any
mismatch requires a separately audited exact-pin MCP package; wildcard,
auto-learn, and bundle-only trust remain forbidden. If the installed app is not
visible in Bootstrap's App List, stop: the installation-form hypothesis is not
proven and neither Observer nor Canary may be changed. See
`docs/TEST-52-C1.4-FIXTURE-INSTALLATION-FORM.md` and
`evidence/host/test52-c1.4-trollstore-ipa-package.json`. TEST-52 remains
NOT_PASS/FAIL_CLOSED; TEST-51 remains device BLOCKED; Phase 6 remains BLOCKED.

**C1.3b Canary proof-sink correction (2026-09-04): HOST/BUILD/PACKAGE PASS;
MANUAL INSTALL AND DEVICE GATE NOT_RUN, device actions 0.** New C1.4 device
evidence proves Bootstrap's enable-for-app path ran for the TrollStore Fixture:
the target app has `.jbroot`, `.prelib`, `.rebuild`, `.tweaked`, `.original`,
and app-backup artifacts. This narrows the prior C1.3 absent global cache file:
it cannot alone prove target injection failed because the TrollStore Fixture is
containerized. C1.3b changes only the Canary proof-sink destination from the
global mobile cache to `HOME/Library/Caches/phoneharness-c1-canary.json`, with
`HOME` obtained inside the target process and no hard-coded container UUID. The
atomic state remains exactly `loaded`, `pid`, monotonic ticks, and own image
path; fixed write result/errno goes only to a non-field diagnostic receipt. The
Fixture-only Filter, Canary-only scope, no UIKit/Foundation, no fields, no
Observer, no IPC/MCP/action interface, TEST-52 contract, TEST-51 device BLOCKED
state, and Phase 6 BLOCKED state remain unchanged. The delivery package must be
manually installed/resprung; then launch the Fixture with Observer OFF and read
only `<Container Path>/Library/Caches/phoneharness-c1-canary.json`. A valid
fixed-schema state can establish only `INJECTION_GATE=PASS`; its absence leaves
loader/constructor diagnosis open. It does not pass TEST-52. See
`docs/TEST-52-C1.3-INJECTION-ISOLATION.md` and
`evidence/host/test52-c1.3b-proof-sink-package-r4.json`.

Diagnostic debug-9 adds the opt-in no-bootstrap route (2026-09-03): new tests
20/20 (18 actual native control-flow Host scenarios, 2 source checks), related
focused Host 178/178, full offline regression 68/68 suites. Compile/link passed
arm64 and arm64e. Final root/root archive has the same 38 entries and file modes
as debug-8, including mcp-root 4755; only the main dylib and Build Identity have
changed data. No runtime authority/provenance standards changed. Package:
`com.witchan.ios-mcp_1.2.2+ph1-13+roothide+debug-9+debug-1+debug_iphoneos-arm64e.deb`;
identity `phb-2739dd553fa0730ff5b17ef6`; SHA-256
`01732dddd3cbe177e3b02a358a86e87f8ec5c8f9bca1aff6ea629043709c815b`.
`DEPLOY_READY=YES` meant Host/build/scope preconditions only; deployment and
Device Gate were NOT_RUN at build completion. The later owner installation and
single-read INSUFFICIENT result are recorded above. Debug-8 package/evidence and
the debug-7/debug-5/debug-4/ph1-12 rollback chain are preserved. TEST-52 remains
NOT_PASS/FAIL_CLOSED; TEST-51 device BLOCKED; Phase 6 BLOCKED; device actions 0.

At that historical snapshot, the planned next gates were:

1. TEST-60 Persistent Conversation Context & Referent Continuity V1, HOST-first.
2. TEST-61 Agent State Projection & Minimal Product Shell.
3. TEST-62 App Intent / App Shortcut ingress.
4. Scheduler / Trigger / Long-running Tasks after the preceding contracts.

Product Experience should begin partially: define information architecture and
a stable redacted client state projection before visual polish. Orb is a state
or entry representation. Dynamic Island and Live Activity present task state,
progress, or pending attention. They never own planning, authorization,
scheduling, or execution.

## FOUNDATION STABILIZATION BATCH 1A (ZCode copy, 2026-08-29)

Scope: host-side only, from the Post-TEST-59 Foundation Stabilization Audit
(`_zcode_workspace/reports/FOUNDATION-STABILIZATION-AUDIT-POST-TEST-59.md` in
this copy). The audit itself is not a TEST-numbered gate. No device action ran
(`device_action_count=0`); all evidence is offline.

Fixed in `phoneharness_agent.py`:

1. Audit P0-4 replan action replay. `TaskCoordinator.replan_dynamic_task` now
   passes session-verified skill ids into `DynamicPlanner.replan_dynamic`, and
   the replanned plan excludes skills whose steps already completed the full
   Risk -> Executor -> Ledger -> Verifier cycle in a superseded revision.
   `DynamicPlan.completed_skill_ids` carries them and `PlanValidator` treats
   them as satisfied dependencies. Previously a replan reset every step to
   PENDING and re-dispatched already-executed external actions.
2. Audit P1-1 Ledger capacity wedge. `ActionObligationLedger` now rotates its
   oldest terminal (VERIFIED/FAILED) record into
   `action-obligations-archive-v1.json` and leaves an idempotent tombstone in
   the primary store, instead of raising "action obligation capacity reached"
   forever once 128 records accumulated. Tombstones keep identity, task
   scoping, and final state, so duplicate references stay blocked and TEST-58
   reconciliation stays consistent; the archive keeps full audit history
   (bounded 256, FIFO). A store saturated with non-terminal obligations still
   fails closed.
3. New fail-closed tests close three audit gaps: ledger duplicate
   `obligation_ref` creates no second record (P2-16); TEST-59 conflicting
   acknowledgement id is rejected with `ACKNOWLEDGEMENT_CONFLICT` (P2-17);
   replan excludes verified skills and never re-dispatches them (P0-4
   regression test); saturated unfinished ledger stays fail-closed.

Evidence: focused 24/24 (TEST-54 runtime file), 11/11 (TEST-45 ledger file),
13/13 (TEST-59 lifecycle file); full offline regression `run_all_tests.py`
59/59 files, 0 failures. Diff snapshots:
`_zcode_workspace/backups/BATCH-1A/`.

The historical audit findings above remain intact. P1-5/P1-6 are now closed
for the bounded host scope recorded in the audit addendum; memory stores and
reachable compatibility paths were deliberately not deleted or merged.
Selected P2 items remain open. TEST-51 remains device Gate `BLOCKED`; TEST-52
remains `NOT_PASS` / `FAIL_CLOSED`. No TEST status changed in this batch; it is
a foundation stabilization fix, not a capability gate.

## FOUNDATION STABILIZATION BATCH 1B (ZCode copy, 2026-08-29 — device side)

Scope: the three P0 device-security fixes from the Post-TEST-59 audit, deployed
to the real iPhone 15 Pro / iOS 17.0 / RootHide + ElleKit device. Full plan and
per-item evidence: `_zcode_workspace/reports/BATCH-1B-PLAN.md`,
`BATCH-1B-PHASE4-DEVICE-GATE-REPORT.md` (this copy).

Deployed build: `com.witchan.ios-mcp_1.2.2+ph1-13+roothide+debug-4+debug`
(sha256 `c8e2f334…19dbe0`). Rollback remains `ph1-12` (sha `d1cb2ce4…`,
untouched). Install was performed manually by the operator via Sileo/dpkg
because AppManager's mcp-root elevation was temporarily broken by a packaging
mistake (see packaging lesson below); `postinst` force-rotates the auth token
and stages a one-time AFC bootstrap copy under `/var/mobile/Media` (deleted
after each read).

1. P0-1 auth: every endpoint (including /health) now requires `X-MCP-Token`
   (constant-time compare, 401 fail-closed, value never logged or echoed).
   Default binding is loopback-only; LAN requires the `allowLan` preference
   (default off). Host transport refuses to call without
   `PHONEHARNESS_MCP_TOKEN`. Verified: correct/missing/wrong token, health
   gating, zero token occurrences in syslog and device log file, loopback
   binding (LAN probe refused), token stable across SpringBoard restarts.
2. P0-2 ldid validator: `mcp-root` validates the ldid shape (argc==4,
   `-S[entitlements] <app-container-target>`); all eight reject shapes return
   126 before setuid; the legal shape passes validation (reaches setuid).
   run_command-spawned children cannot elevate in this RootHide context
   (`setgid(0) failed` = pre-existing environment behavior, identical in
   ph1-12); production elevation was exercised end-to-end by the deployment's
   own dpkg install via AppManager→mcp-root.
3. P0-3 upload hardening: upload dir repaired/enforced 0700, files 0600,
   stale (>24h) uploads purged at server start and before every upload;
   immutable-directory test produced a fail-closed rejection; purge failure
   leaves the file in place (never fakes deletion).
4. P2-12: AX string error-placeholder matching narrowed to the node-source
   sentinels; device diagnostics confirm placeholders still classify as
   `error_object` (no detection loss, no TEST-52 weakening).
5. P2-13: semantic availability probe bounded at 300 leaves;
   `semantic_probe_limit`/`semantic_probe_skipped_count` now surface in the
   response (the first build omitted them from the response key whitelist —
   caught and fixed by this gate cycle).
6. P2-14 / Gate E: read-only TEST-52 device gate re-run — 9 semantic fields on
   the current screen, `direct_state_count=0`, `eligible_field_count=0`,
   FAIL exactly as documented for the zero-eligible observation blocker.
   **TEST-51 stays device Gate `BLOCKED`; TEST-52 stays `NOT_PASS` /
   `FAIL_CLOSED`; no TEST status changed.**

Core regression after deployment: tools/list 46 tools, frontmost detection,
plain and semantic get_ui_elements, launch_app (Settings), tap_element
(Settings search field, text-matched), input_text, and the governed
Context-to-Action device gate (real PhoneHarness launch, `status=PASS`,
`device_action_count=1`) all behaved. One pre-existing tool-reliability gap
was OBSERVED (not caused by this batch): `input_text` can report success
without delivering text (no delivery verification at tool level; the governed
verifier catches it via observation). Recorded as P2 for a future batch.

Packaging lesson (mandatory for future builds): injecting maintainer scripts
via `dpkg-deb -R/-b` requires `--root-owner-group`, otherwise the data tar
owner becomes uid 501 and setuid helpers silently lose elevation. The first
debug-4 install failed exactly this way and was recovered by the operator.

Offline regression: 60/60 files (59 existing + new
`test-agent-mcp-auth-boundary-unit.py`), 0 failures.
`device_action_count` for the whole Batch 1B phase: 108 logged device-side
actions (gates, probes, retries, cleanups) — see
`_zcode_workspace/diagnostics/batch-1b/gates/phase4c-actions.jsonl`.

## FOUNDATION STABILIZATION BATCH 1C (ZCode copy, 2026-08-29 — input_text contract honesty)

Deployed build `1.2.2+ph1-13+roothide+debug-5+debug` (sha256 `f5977324…`).
Device-side `input_text` / type / pressKey now return structured responses
with a constant `delivery:"unverified"` and no `verified` field, plus a
`no_target` guard in `TextInputManager.m`. Host tool descriptions rewritten to
match. Live proof on device (Gate T1): `dispatched=true` while an independent
value_match observation showed the text did NOT land — `accepted ≠ dispatched
≠ delivered ≠ verified` is now enforced by the contract itself. Gates: T1
PASS, T2 BLOCKED (no natural pid<=0 state constructible; guard locked by unit
test), T3/T4/T5 PASS (contract level). Full per-item evidence:
`_zcode_workspace/reports/BATCH-1C-PHASE4C-DEVICE-GATE-REPORT.md`. New unit
suite `test-agent-text-input-contract-unit.py` (13/13). Offline regression
61/61. Batch device actions: 38. TEST-51/52/49/50 statuses unchanged.

## INPUT_TEXT ROOT-CAUSE ISOLATION BATCH 1D (ZCode copy, 2026-08-29)

Experiment batches (recorded as Batch Gates, not TEST-xx). BKS routing A/B on
device (debug-6): broadcast vs `BKSHIDEventSendToProcess` targeted — both arms
dispatch-accepted, zero landing across 5 text scenarios → routing is NOT the
root cause; experiment source restored to debug-5 state. E0/E1 (debug-7, adds
a token-gated hidden `exp_keycode_tap` entry): with the third-party WeChat
keyboard focused, neither Unicode (type 30) nor keycode (type 3) events land;
after the operator switched to the Apple Pinyin keyboard, the keycode event
WAS consumed (composition bar + candidates appeared — PROVEN) while Unicode
never was. Conclusion: the failure lives in the iOS 17 synthetic-keyboard-event
consumption/trust layer; keycode delivery works only on Apple-family keyboards.
Full reports: `_zcode_workspace/reports/BATCH-1D-*.md`, evidence
`_zcode_workspace/diagnostics/batch-1d/gates/`. Device actions ≈178 across
1D. TEST statuses unchanged.

## INPUT_METHOD_INDEPENDENT INPUT BATCH 1E (ZCode copy, 2026-08-29)

Product axiom: `input_text` must be input-method independent; the user may
switch keyboards freely and the Apple keyboard is never a precondition.
Real-device strategy experiments: S2 (IME-UI touch: key tap → composition →
candidate → commit) works on Apple Pinyin 9-key/QWERTY, is BLOCKED on WeChat
(candidates not AX-exposed); S4 (clipboard bridge: set_clipboard → long-press
→ paste) delivered on ALL THREE keyboard states (landed:true via search-result
evidence) — the only proven input-method-independent delivery, at the cost of
a documented 3-6s clipboard exposure window. Host-side
`InputTextOrchestrator` implemented as a pure append (~290 lines, zero deleted
lines) in `phoneharness_agent.py`: strategy selection (short ASCII on Apple
keyboards → S1 keycode first; everything else → S4; `sensitive=true` forbids
S4 → `no_safe_strategy` on failure), SET semantics (field cleared before every
attempt so fallback can never produce `hellohello`), attempt ledger without
plaintext, and three `CapabilityMethodDefinition`s reusing the TEST-47 method
registry. New suite `test-agent-input-orchestrator-unit.py` (13/13); offline
regression 62/62. **Phase 5 is host-only and NOT device-gated yet: no build,
no deploy, DEVICE_ACTION_COUNT=0. The Batch 1E Phase 6 real-device Gate is the
next recommended step and has NOT run — no device PASS exists for the
orchestrator.** Reports: `_zcode_workspace/reports/BATCH-1E-*.md`.

## POST-ZCODE 1E-P5 GOVERNANCE CLOSURE (2026-09-03)

This historical note superseded the earlier Phase 6 recommendation above, not
its device experiment evidence. `GOVERNANCE_CLOSURE=PASS` is HOST-only:
88/88 existing focused tests plus 34/34 new closure tests; complete offline
regression 64/64 suites, 0 failures. Report:
`_zcode_workspace/reports/BATCH-1E-P5-GOVERNANCE-CLOSURE-REPORT.md`.

Input target authority is now issued and revalidated by existing RiskController
from owned current Context and direct same-leaf TEST-52 evidence. Constructed
or copied target/authorization fields do not grant execution. Input verification
requires fresh same-target direct value evidence, not page text or page
non-emptiness. Dispatch accounting uses actual Executor port invocations.
Existing typed bindings, PlanExecutor and per-action Ledger remain in use.

Input methods remain CANDIDATE; sensitive S4 is excluded and the clipboard Risk
policy is unchanged. Unsupported clear/paste controls remain blocked. TEST-51
Host/E2E PASS / Device BLOCKED and TEST-52 NOT_PASS / FAIL_CLOSED are unchanged.
`TAKEOVER_VALIDATION_READY=YES` means ready for re-validation, not device approval.
Phase 6 remains BLOCKED. WDA research is unchanged; no WDA/device gate, build,
deploy, or device action occurred (`DEVICE_ACTION_COUNT=0`). Golden baseline
untouched; pre-existing work preserved.

## ZCODE FINAL HANDOFF (2026-09-03)

ZCode tenure closed. Full consolidated handoff for any successor AI:
`_zcode_workspace/reports/ZCODE_FINAL_HANDOFF.md` (starting baseline, work
log, files changed, bug ledger, per-test evidence, architecture decisions,
security impact, current state, recommended next mainline) and
`_zcode_workspace/reports/ZCODE_CODE_CHANGE_SUMMARY.md` (per-file change
rationale with diff archives under `_zcode_workspace/backups/ZCODE-FINAL/`).
Entry point for a new AI: `_zcode_workspace/reports/NEXT_AI_START_HERE.md`.
A self-contained curated review bundle for handing evidence to an external AI
also exists: `_zcode_workspace/PhoneHarness-ZCode-AI-Review.zip` with a
per-file `AI_REVIEW_MANIFEST.md` (no secrets, no build artifacts, no device
images).
Nothing was committed, staged, or stashed during the tenure; the original
baseline at `/Users/charles/ios-mcp-phoneharness` was never modified.

## TEST-52 Track C1 Historical State (2026-09-04)

**C1.3b injection proof: DEVICE_PROVEN, narrowly scoped.** The owner manually
installed the C1.3b canary into the TrollStore C1.4 Fixture form and, with the
Observer OFF, read a valid container-local fixed canary receipt:
`loaded=true`, PID `59776`, monotonic timestamp, and an image path under
`TweakInject/PHC1InjectionCanary.dylib`. This proves only target-app
RootHide/ElleKit injection and constructor execution for the exact Fixture
bundle/filter. It does not prove Observer load, listener, IPC, field capture,
same-leaf evidence, TEST-52 authorization, or Phase 6. Device actions remain 0.

**C1.5 Observer-only reintroduction: HOST/BUILD/PACKAGE PASS; DEVICE NOT_RUN.**
The independent package contains exactly `PHC1Observer.dylib` and the single
Fixture-only filter; it contains no Fixture, Canary, MCP, action endpoint, or
execution capability. Its default-off observer preserves all C1.2 startup
breadcrumbs but uses a C1.5-only compile-time home-derived sink:
`NSHomeDirectory()/Library/Caches/phoneharness-c1-startup.json`. The final
audited package is
`diagnostics/test52-c1-observer/packages/com.charles.phoneharness.test52.c1.observer_0.1.0-c1.5-20260904-1+observer-only-audited_iphoneos-arm64e.deb`,
SHA-256 `ecf4abc725bcee2d26a6762c84d29d920961a65bf8e3cd782727c2602814d2f0`.
C1 plus C1.5 host/native tests are 47/47 PASS, the canary regression is 12/12
PASS, and full Host regression is 69/69 PASS. Package evidence:
`evidence/host/test52-c1.5-observer-only-package.json`.

Manual install is the only next deployment step. It must leave the TrollStore
Fixture and current MCP package in place. The first future device stage remains
Observer OFF only: confirm container-local `init_entered`, `enabled_seen=false`,
and no listener. Before any IPC check, re-read actual runtime Fixture CDHash;
the current MCP exact pin is unverified after the TrollStore installation form.
Mismatches require a fresh reviewed exact-pin MCP package. No wildcard,
auto-learn, or bundle-only fallback is permitted. TEST-52 remains
NOT_PASS/FAIL_CLOSED, TEST-51 device BLOCKED, Phase 6 BLOCKED, and
`device_action_count=0`.

**C1.6 container-local IPC: HOST/BUILD/PACKAGE PASS; DEVICE NOT_RUN.** The
C1.5 listener failed only at global-socket `bind(...)=EPERM` in the
containerized TrollStore Fixture. C1.6 changes its new Observer-only build to
use `NSHomeDirectory()` for the socket. MCP resolves only the fixed Fixture
bundle via existing local app metadata and validates the derived private socket
with `lstat`; it retains kernel peer credentials, canonical executable, bundle,
exact CDHash, and PID/version rechecks. Wrong containers, symlinks, wrong
bundle, unsafe sockets, and stale no-listener endpoints fail closed.

Observer package, not installed by this work:
`diagnostics/test52-c1-container-ipc/packages/com.charles.phoneharness.test52.c1.observer_0.1.0-c1.6-20260904-1+container-ipc-audited-r3_iphoneos-arm64e.deb`
(SHA-256 `32e3e99e2aaafc4e395aa29eb9fa96df69df2ebcfe51ecf93b68659217a39160`).
Fresh device evidence now records the TrollStore Fixture arm64e CDHash
`38b8d7850cfeb15614f5525c1b133833eaada569`. The exact C1.6 runtime-pin r4
package is artifact-ready for a separately approved manual installation:
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.6+container-ipc-runtime-pin-r4+debug_iphoneos-arm64e.deb`
(SHA-256 `37ed41deec64be67930c5bc6ae54d1597840539f790a2f5be8adceb46d30c67b`).
It embeds only that pin; the prior `6d3451182910f07efcfc8b106a4edaa4427b7a09`
is absent from its active C1.6 source/build/package. It remains an
observation-only diagnostic with no action endpoint, and is not an accept-any
fallback.

C1.6 evidence: C1 `40/40`, C1.6 `7/7`, previous runtime/exact-pin `14/14`,
fresh exact-runtime-pin `6/6`, C1.5 `7/7`, canary `12/12`, and full offline
regression `69/69` PASS. No C1.6
device action, installation, IPC, or field observation occurred. TEST-52 stays
NOT_PASS/FAIL_CLOSED; TEST-51 device remains BLOCKED; Phase 6 stays BLOCKED.
See `docs/TEST-52-C1.6-CONTAINER-LOCAL-IPC.md` and
`diagnostics/test52-c1-container-ipc/evidence/host/test52-c1.6-container-ipc-observer-package-r3.json` and
`diagnostics/test52-c1/packages/C1.6-CONTAINER-IPC-PIN-DISABLED-R3-EVIDENCE.json` and
`diagnostics/test52-c1/packages/C1.6-CONTAINER-IPC-RUNTIME-PIN-R4-EVIDENCE.json`.

**C1.7 short container socket: HOST/BUILD/PACKAGE PASS; DEVICE NOT_RUN.** C1.6
device Stage B established `bind(...)=ENAMETOOLONG` for the longer container
cache path. C1.7 replaces only the transport suffix with fixed
`NSHomeDirectory()/tmp/pc/p.sock`; it does not modify the TrollStore Fixture or
its exact peer pin. Both Observer and MCP reject paths that cannot retain the
terminating NUL in `sockaddr_un.sun_path`. The private `tmp/pc` directory is
`0700`, the socket is `0600`, and existing stale-endpoint, trusted bundle
resolution, kernel peer, canonical executable, PID/version, and exact-CDHash
checks remain intact.

Manual-install artifacts, not installed by this work:
`diagnostics/test52-c1-short-socket/packages/com.charles.phoneharness.test52.c1.observer_0.1.0-c1.7-20260904-1+short-socket-audited-r1_iphoneos-arm64e.deb`
(SHA-256 `9e84c7a6187878a554d7a1bac3cab64db032fc0353a3669691041267db81bb52`) and
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.7+short-socket-runtime-pin-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `fdfcca5485fabfd6a97bcee6c99fa669e918584ae1d10a3ba9f8611b7daf87cd`).
C1.7 retains only the fresh runtime pin
`38b8d7850cfeb15614f5525c1b133833eaada569`; the historical C1.6 r4 package is
preserved as evidence but is superseded for transport by C1.7. C1.7 evidence:
short socket/artifact `7/7`, C1 `40/40`, C1.6 `7/7`, fresh pin `6/6`, prior pin
`14/14`, C1.5 `7/7`, Canary `12/12`, and full offline regression `69/69` PASS.
TEST-52 remains NOT_PASS/FAIL_CLOSED; TEST-51 device remains BLOCKED; Phase 6
remains BLOCKED; no device action occurred. See
`docs/TEST-52-C1.7-SHORT-CONTAINER-SOCKET.md` and
`diagnostics/test52-c1-short-socket/evidence/host/test52-c1.7-short-socket-observer-package-r1.json` and
`diagnostics/test52-c1/packages/C1.7-SHORT-SOCKET-RUNTIME-PIN-R1-EVIDENCE.json`.

**C1.8 MCP startup regression differential: HOST/BUILD/PACKAGE PASS; DEVICE
NOT_RUN.** The last actual device `/health` PASS is debug-9, package SHA-256
`01732dddd3cbe177e3b02a358a86e87f8ec5c8f9bca1aff6ea629043709c815b`.
Its injected dylib links RootHide loader-relative `libroothide` and
`libsubstrate`. The C1.7 MCP dylib retained its constructor and SpringBoard
filter but was built without `THEOS_PACKAGE_SCHEME=roothide`, so both slices
instead linked rootful CydiaSubstrate. This is the minimal build-chain root
cause for the missing RootHide server startup path; no RootHide/device global
diagnosis or TEST-52 contract change was made.

C1.8 fixes only the isolated diagnostic generation and package audit. Generated
builds now force RootHide scheme, are tweak-only, and C1.8 requires
`PH_TEST52_C1_DIAGNOSTIC=1`. The packager rejects a dylib missing either
RootHide linkage, startup symbols, the exact current pin, or a C1 runtime
contract. The rejected C1.8-r1 build omitted the C1 diagnostic macro and is
not deployable. C1.8-r2 was host-valid, but C1.8-r3 adds an explicit binary
audit of `MCPServer startOnPort:` in both architectures. The final C1.8-r3
package SHA-256 is `a73da1969a7471ecf143bf235f758bf1a72e12a0fb54b11fc77a3af08a4022b0`.
It retains C1.7 `$HOME/tmp/pc/p.sock`, exact pin
`38b8d7850cfeb15614f5525c1b133833eaada569`, and all peer/PID/version/bundle/
canonical-executable/CDHash checks. The revoked
`6d3451182910f07efcfc8b106a4edaa4427b7a09` pin is absent. C1.8 `6/6`, C1
`40/40`, C1.7 `7/7`, C1.6 `7/7`, exact pin `6/6`, and full Host `69/69` are
PASS. No install or device action occurred.

This does not establish that port 8090 now listens: C1.8 is only a deploy-ready
candidate. TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device
BLOCKED, Phase 6 remains BLOCKED, and field gate remains NOT_RUN. See
`docs/TEST-52-C1.8-MCP-STARTUP-REGRESSION.md` and the final C1.8-r3 package
evidence.

**C1.9 MCP auth provisioning: HOST/BUILD/PACKAGE PASS; DEVICE NOT_RUN.**
Subsequent manual C1.8 deployment restored the RootHide MCP listener on the
device: USB forwarding and device port `8090` listened, and `/health` without
a credential correctly returned `401`. This is a narrowly scoped startup and
fail-closed-auth device result; it does not establish positive credential
acceptance, C1 IPC, field evidence, TEST-52 authorization, or Phase 6.

The remaining authorization blocker was traced to the prior package
maintainer script, not the token shape or the C1.8 startup path. It used
macOS-style `plutil -replace/-string` syntax that the actual RootHide device
interpreted as an unexpected `replace` preference key, and it rotated a token
on every installation. C1.9 adds the smallest fix: device-proven
`plutil -key authToken -value <redacted> -type string` provisioning, valid
credential preservation, conditional cleanup of only the malformed legacy
`replace` key, and metadata-only source/length diagnostics. Token values and
hashes are never logged.

C1.9 keeps C1.8 RootHide startup linkage, C1.7
`NSHomeDirectory()/tmp/pc/p.sock`, and the exact active Fixture CDHash pin
`38b8d7850cfeb15614f5525c1b133833eaada569`; the revoked
`6d3451182910f07efcfc8b106a4edaa4427b7a09` pin is absent from its active
dylib. Its candidate package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.9+auth-provisioning-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `38c4df84b4ab029502f54745a659ae9b03090685d0bfe58f55aae603ccdb5a09`).
It is root-owned/non-world-writable, retains `mcp-root` mode `4755`, and adds
only control metadata, `DEBIAN/postinst`, `ios-mcp.dylib`, and build identity
relative to debug-9. No Fixture, Canary, wildcard pin, or action capability is
included.

C1.9 auth provisioning `7/7`, existing MCP auth boundary `7/7`, C1.9 package
audit `5/5`, C1 core `40/40`, C1.8 `6/6`, C1.7 `7/7`, C1.6 container `7/7`,
and C1.6 exact pin `6/6` are PASS; full offline Host regression is `70/70`
PASS. No C1.9 installation, device contact, action, or token trial occurred
(`DEVICE_ACTION_COUNT=0`). See `docs/TEST-52-C1.9-MCP-AUTH-PROVISIONING.md`
and `diagnostics/test52-c1/packages/C1.9-AUTH-PROVISIONING-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.10 native fail-closed stage observability: HOST/BUILD/PACKAGE/FOUNDATION
PASS; DEVICE NOT_RUN.** A prior authenticated read-only request reached native
C1 but received only the intentionally generic `UNAVAILABLE/BLOCKED/
NATIVE_DIAGNOSTIC` envelope. C1.10 preserves that envelope and adds only two
non-sensitive fields: a fixed `failure_stage` enum and a fixed errno-class
`failure_code`. The stage set covers endpoint resolution, socket discovery and
connect, peer/PID/executable/bundle/CDHash checks, nonce/packet exchange,
snapshot parse/contract, foreground epoch, and unknown internal failure. It
returns no token, token hash, nonce, packet, field content, path, signing
material, address, or stack detail; host `MCPCallError` preserves the structured
stage solely for diagnostic attribution.

The C1.10 package keeps the current exact Fixture pin
`38b8d7850cfeb15614f5525c1b133833eaada569`, excludes revoked pin
`6d3451182910f07efcfc8b106a4edaa4427b7a09`, preserves C1.7 short container
socket transport, and changes no Fixture, Observer, peer/nonce/snapshot
contract, normalizer, Risk, Executor, or TEST-52 criterion. C1 focused suites
are `73/73 PASS`, full Host regression is `71/71 PASS`, and the Foundation
Regression Gate passed every linkage, startup, auth, pin, package delta,
postinst, ownership, and mode check. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.10+stage-observability-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `8de417604e73535e6425f71ca7c018789306e3c2075e2910081853ebabc0b2ee`).
It was not installed or sent to the device and made zero device actions. See
`docs/TEST-52-C1.10-NATIVE-STAGE-OBSERVABILITY.md` and
`diagnostics/test52-c1/packages/C1.10-STAGE-OBSERVABILITY-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.11 canonical-executable sub-branch observability: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** A valid later C1.10
read-only device request met its operator-attested Fixture foreground and
Observer-ON preconditions and authenticated `/health=200`, then returned the
existing fail-closed `CANONICAL_EXECUTABLE` stage with generic code `NONE`.
C1.11 changes only diagnostic attribution within that already-existing stage.
It adds one allowlisted `failure_subcode` for the five current branches:
`EXPECTED_PATH_INVALID`, `BUNDLE_EXECUTABLE_MISMATCH`,
`EXECUTABLE_METADATA_REJECTED`, `PEER_PIDPATH_UNAVAILABLE`, or
`PEER_PATH_MISMATCH`.

No canonical executable check changes: there is no `realpath`, `/var` alias
normalization, RootHide special case, resolver fallback, bundle-containment
change, or relaxation of kernel peer credentials, PID/version, bundle,
literal-path, or exact CDHash requirements. The current exact Fixture pin is
still `38b8d7850cfeb15614f5525c1b133833eaada569`; revoked pin
`6d3451182910f07efcfc8b106a4edaa4427b7a09` remains absent. C1.11 has no
Fixture, Observer, socket, nonce/snapshot, Risk, Executor, or TEST-52 contract
change and no device request or action. Its package candidate is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.11+canonical-subcodes-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `1f905630bc36ff72436efe80863117d758895a6e0f9c960126e1ab1c829220ea`).
See `docs/TEST-52-C1.11-CANONICAL-EXECUTABLE-SUBCODES.md` and
`diagnostics/test52-c1/packages/C1.11-CANONICAL-SUBCODES-R1-EVIDENCE.json`.
C1 core `43/43`, exact-pin `5/5`, runtime-pin `9/9`, C1.8 `6/6`, C1.9 `5/5`,
C1.10 `5/5`, and C1.11 `5/5` are `78/78 PASS`; complete offline Host
regression is `71/71 PASS`; and the Foundation Regression Gate is PASS for
the debug-9 baseline, RootHide linkage/scheme, startup, auth, filters,
`mcp-root=4755`, exact/revoked pin checks, package delta, device-tool script
contract, and archive ownership/modes. No C1.11 package installation, device
request, or action occurred (`DEVICE_ACTION_COUNT=0`).
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.12 executable metadata predicate observability: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** The valid C1.11 device result narrowed the
current native blocker to `CANONICAL_EXECUTABLE / EXECUTABLE_METADATA_REJECTED
/ NONE`. C1.12 changes only that diagnostic attribution: the unchanged
`PHC1SafeRegularFile` checks now report `EXECUTABLE_LSTAT_FAILED`,
`EXECUTABLE_NOT_REGULAR`, `EXECUTABLE_OWNER_MISMATCH`, or
`EXECUTABLE_GROUP_OR_OTHER_WRITABLE`.

The exact-entry `lstat`, `S_ISREG`, `st_uid == getuid()`, no group/world write,
live LaunchServices resolution, containment, literal peer path, kernel peer,
PID/version, exact CDHash, nonce, snapshot, and epoch requirements are not
relaxed. No path, UID, GID, mode, UUID, raw errno message, token/hash, nonce,
or metadata value is returned. The current exact Fixture pin remains
`38b8d7850cfeb15614f5525c1b133833eaada569`, and revoked pin
`6d3451182910f07efcfc8b106a4edaa4427b7a09` is absent.

C1 focused suites are `83/83 PASS`, complete offline Host regression is
`71/71 PASS`, and the Foundation Regression Gate passed the immutable debug-9
baseline, RootHide scheme/linkage, startup/auth, SpringBoard filter,
`mcp-root=4755`, exact/revoked pins, four-file delta, postinstall contract, and
archive ownership/modes. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.12+metadata-subcodes-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `71d925a478bcb8dcbf22cf69ff81d1750039797882dda02dcf43d34d57d2e25c`).
No installation, device request, or action occurred (`DEVICE_ACTION_COUNT=0`).
See `docs/TEST-52-C1.12-EXECUTABLE-METADATA-PREDICATES.md` and
`diagnostics/test52-c1/packages/C1.12-METADATA-SUBCODES-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.13 executable owner predicate security fix: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** A valid C1.12 device request proved the
remaining canonical-executable blocker was `EXECUTABLE_OWNER_MISMATCH` from
`st_uid == getuid()`. Security review classified that equality as an invalid
platform assumption: `getuid()` identifies the MCP/SpringBoard process, not
the separately installed TrollStore target App.

C1.13 removes only that cross-process owner equality. Exact-entry `lstat`,
regular-file and no group/world write requirements, live LaunchServices
resolution, bundle containment, literal peer executable equality, kernel peer
credentials, PID/version, exact CDHash, nonce, snapshot, and foreground epoch
remain mandatory. No fixed UID allowlist, fallback, path normalization,
Fixture/Observer change, TEST-52 relaxation, or action path was added.

C1 focused suites are `88/88 PASS`, complete offline Host regression is
`71/71 PASS`, and the Foundation Regression Gate passes all checks against the
immutable debug-9 baseline. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.13+owner-predicate-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `aabd4364b8967fe63997cd9eeb22520ad2a8326d7e307dc0ee25aef64e7e2a43`).
No installation, device request, or action occurred (`DEVICE_ACTION_COUNT=0`).
See `docs/TEST-52-C1.13-EXECUTABLE-OWNER-PREDICATE.md` and
`diagnostics/test52-c1/packages/C1.13-OWNER-PREDICATE-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.14 stale socket residual errno fix: HOST/BUILD/PACKAGE/FOUNDATION PASS;
DEVICE NOT_RUN.** After C1.13 passed executable metadata, canonical executable,
and bundle identity on device, Observer lifecycle evidence isolated the next
failure to stale-endpoint startup. A refused stale socket was securely
classified and successfully unlinked, but residual `ECONNREFUSED` in `errno`
was incorrectly consumed by a later unconditional check, preventing socket
creation.

C1.14 derives `lstat`, `connect`, and `unlink` state exclusively from each
syscall return value and captures `errno` only immediately after failure.
Successful stale removal now proceeds directly toward socket creation even if
`errno` retains the earlier connect error. All exact-path, `lstat`, socket
type, owner, mode, container, live-endpoint, symlink, unsafe-entry, and
fail-closed checks remain unchanged. The `$HOME/tmp/pc/p.sock` path, Fixture,
MCP receiver, exact runtime pin, peer/PID/bundle/path/CDHash checks,
nonce/snapshot contract, authorization, and C1.13 owner fix are unchanged.

Dedicated C1.14 regression is `8/8 PASS`, C1 focused suites are `96/96 PASS`,
complete offline Host regression is `71/71 PASS`, and the Foundation
Regression Gate passes every check against immutable debug-9 using the
unchanged C1.13 MCP package. The audited Observer-only package is
`diagnostics/test52-c1-stale-errno/packages/com.charles.phoneharness.test52.c1.observer_0.1.0-c1.14-20260905-1+stale-errno-r1-audited_iphoneos-arm64e.deb`
(SHA-256 `6f723ef0318987433d17344399b99c44abf57aafe644c061c676387eae22babf`).
It contains only the arm64/arm64e Observer dylib and Fixture-only filter and
was rebuilt with root ownership/group metadata. No install, device request, or
action occurred (`DEVICE_ACTION_COUNT=0`). See
`docs/TEST-52-C1.14-STALE-SOCKET-RESIDUAL-ERRNO.md` and the package evidence
under `diagnostics/test52-c1-stale-errno/evidence/host/`.

TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.15 peer-path identity observability: HOST/BUILD/PACKAGE/FOUNDATION PASS;
DEVICE OBSERVABILITY PASS / AUTH FAIL_CLOSED.** C1.14 device evidence passed listener/socket discovery,
connect, and kernel peer credential acquisition, then failed closed at
`CANONICAL_EXECUTABLE / PEER_PATH_MISMATCH`. Source review found that the
expected executable is built from a standardized live LaunchServices bundle
path plus `CFBundleExecutable`, while the peer candidate is the raw
`proc_pidpath_audittoken` result. Existing evidence does not prove whether the
actual difference is `/var` versus `/private/var`, standardization, same-file,
realpath, or a genuinely different file.

C1.15 therefore adds diagnostic-only, allowlisted `path_identity` categories:
`RAW_EQUAL`, `VAR_PRIVATE_ALIAS`, `STANDARDIZED_EQUAL`,
`SAME_FILE_IDENTITY`, `REALPATH_EQUAL`, `DIFFERENT_FILE`, and `UNAVAILABLE`.
C1.15's deployed package retained the original literal `strcmp` authorization
gate, so every mismatch returned `BLOCKED/UNAVAILABLE` before CDHash, nonce,
or snapshot work. C1.16 supersedes that decision only for the subsequently
device-proven strict alias class.
No raw path, installation UUID, filesystem identity, UID, token, nonce, or
field content is returned. C1.13 owner handling, C1.14 stale-errno handling,
kernel peer/PID/version, bundle containment, exact current CDHash, revoked-pin
absence, and all fail-closed contracts remain unchanged.

C1.15 tests are `8/8 PASS`; existing C1 tests are `88/88 PASS`; C1.14 tests are
`8/8 PASS`; combined C1 focused/security is `104/104 PASS`; full Host regression
is `71/71 PASS`; and the Foundation Regression Gate is PASS against immutable
debug-9. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.15+path-identity-observability-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `a17169f35b566aa8d55dbba25158b80f40631a91eb15834bf798dc507770cd92`).
No install, device request, or device action occurred (`DEVICE_ACTION_COUNT=0`).
See `docs/TEST-52-C1.15-PEER-PATH-IDENTITY-OBSERVABILITY.md` and
`diagnostics/test52-c1/packages/C1.15-PATH-IDENTITY-OBSERVABILITY-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

The subsequent approved one-shot C1.15 device Gate returned
`CANONICAL_EXECUTABLE / PEER_PATH_MISMATCH` with
`path_identity=VAR_PRIVATE_ALIAS`. Executable metadata, bundle identity,
socket discovery/connect, and kernel peer credentials passed; exact CDHash,
nonce, snapshot, and foreground-epoch verification were not reached. The
result remained `BLOCKED/UNAVAILABLE`, no field Gate ran, and
`DEVICE_ACTION_COUNT=0`.

**C1.16 strict `/var/` and `/private/var/` executable alias: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** C1.16 replaces only the peer executable
literal-equality decision with a dedicated helper. It accepts raw equality or
the exact bidirectional `/var/<non-empty remainder>` and
`/private/var/<same remainder>` alias. It rejects false prefixes, empty or
different remainders, traversal/non-clean paths, basename/suffix matching, and
does not use `realpath`, inode identity, or general symlink resolution for
authorization.

All later identity checks remain mandatory: exact CDHash verification still
follows the path gate, and the current runtime pin remains
`38b8d7850cfeb15614f5525c1b133833eaada569`; the revoked pin remains absent.
C1.13 owner handling, C1.14 stale-errno handling, trusted LaunchServices and
bundle containment, kernel peer/PID/version, nonce/snapshot, foreground epoch,
and fail-closed behavior are retained.

C1.16 tests are `9/9 PASS`; existing C1 tests are `88/88 PASS`; retained C1.14
and C1.15 tests are `8/8 PASS` each; full Host regression is `71/71 PASS`; and
the Foundation Regression Gate reports `deploy_ready=true`. The build-only
package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.16+strict-var-private-alias-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `5ed927f1b51243067f2b33cba5bd0a40ed647bce9b6e3ffb0d50f907b45a8f9d`).
No install, device request, or device action occurred. See
`docs/TEST-52-C1.16-STRICT-VAR-PRIVATE-EXECUTABLE-ALIAS.md` and
`diagnostics/test52-c1/packages/C1.16-STRICT-VAR-PRIVATE-ALIAS-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, and the field Gate remains NOT_RUN.

**C1.17 LOCAL_PEERTOKEN credential observability: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** C1.17 splits the ambiguous peer-token branch
into `LOCAL_PEERTOKEN_SYSCALL_FAILED`, `LOCAL_PEERTOKEN_SIZE_MISMATCH`, and
`PEER_PID_INVALID`, and reports `INITIAL` versus `POST_PACKET` authentication.
It captures errno only after an actual failed `getsockopt`; a successful call
with the wrong returned size reports `failure_code=NONE`. The fail-closed
envelope and all credential, PID/version, path, bundle, exact-CDHash,
nonce/snapshot, and foreground-epoch requirements remain unchanged.

C1.17 tests are `9/9 PASS`, existing C1 tests are `88/88 PASS`, retained
C1.14/C1.15/C1.16 tests are `8/8`, `8/8`, and `9/9` PASS, full Host regression
is `71/71 PASS` twice, and the Foundation Regression Gate reports
`deploy_ready=true`. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.17+peer-credential-observability-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `9c3e97b1d3ce96cf0e3bcf433e31353ab3bbac15066a61fd7ff1170eadb1262a`).
No installation, device request, or device action occurred. See
`docs/TEST-52-C1.17-LOCAL-PEERTOKEN-CREDENTIAL-OBSERVABILITY.md` and
`diagnostics/test52-c1/packages/C1.17-PEER-CREDENTIAL-OBSERVABILITY-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, the field Gate remains NOT_RUN, and C1.16 alias remains device
NOT_VERIFIED.

**C1.18 LOCAL_PEERTOKEN exact errno observability: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** C1.18 preserves C1.17 credential behavior
and adds allowlisted `EINVAL`, `ENOTCONN`, `EBADF`, `ENOTSOCK`,
`ENOPROTOOPT`, and `EOPNOTSUPP` failure codes only after an actual failed
`getsockopt(LOCAL_PEERTOKEN)`. Successful calls ignore residual errno, and
audit-token size mismatch remains independent of errno. `INITIAL` and
`POST_PACKET` attribution and all fail-closed identity checks are unchanged.

C1.18 tests are `11/11 PASS`, existing C1 tests are `88/88 PASS`, retained
C1.14/C1.15/C1.16/C1.17 tests are `8/8`, `8/8`, `9/9`, and `9/9` PASS, full
Host regression is `71/71 PASS` twice, and the Foundation Regression Gate
reports `deploy_ready=true`. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.18+peer-credential-exact-errno-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `dba9cb6489c67c3284e42239bb3b6951e74c2e7ccdecf7fda5914d68469d23f8`).
No installation, device request, or device action occurred. See
`docs/TEST-52-C1.18-LOCAL-PEERTOKEN-EXACT-ERRNO-OBSERVABILITY.md` and
`diagnostics/test52-c1/packages/C1.18-PEER-CREDENTIAL-EXACT-ERRNO-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, the field Gate remains NOT_RUN, and C1.16 alias remains device
NOT_VERIFIED.

**C1.19 STANDARDIZED_EQUAL lexical observability: HOST/BUILD/PACKAGE/
FOUNDATION PASS; DEVICE NOT_RUN.** C1.19 adds only redacted clean-status,
lexical-difference, and transformation-side enums for a fail-closed
`STANDARDIZED_EQUAL/PEER_PATH_MISMATCH`. It distinguishes exact dot, dot-dot,
duplicate-separator, trailing-separator, multiple-transform, other, and
unavailable cases without returning paths or components.

`PHC1ExecutablePathsEquivalent()` is unchanged: only raw equality and the
strict C1.16 `/var` to `/private/var` alias can pass. Generic standardized,
realpath, inode, basename, suffix, or traversal normalization remains
diagnostic-only and cannot authorize. All peer credential, PID/version,
bundle, exact-CDHash, nonce/snapshot, foreground-epoch, and fail-closed checks
remain mandatory.

C1.19 tests are `11/11 PASS`, existing C1 tests are `88/88 PASS`, retained
C1.14/C1.16/C1.17/C1.18 tests are `8/8`, `9/9`, `9/9`, and `11/11` PASS, full
Host regression is `71/71 PASS` twice, and the Foundation Regression Gate
reports `deploy_ready=true`. The build-only package is
`diagnostics/test52-c1/packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+c1-1.19+standardized-lexical-observability-r1+debug_iphoneos-arm64e.deb`
(SHA-256 `bc44602eec80cc4f496b4b481071e35d45f9e474732dc83f373bd42058e1c512`).
No installation, device request, or device action occurred. See
`docs/TEST-52-C1.19-STANDARDIZED-EQUAL-LEXICAL-OBSERVABILITY.md` and
`diagnostics/test52-c1/packages/C1.19-STANDARDIZED-LEXICAL-OBSERVABILITY-R1-EVIDENCE.json`.
TEST-52 remains NOT_PASS/FAIL_CLOSED, TEST-51 remains device BLOCKED, Phase 6
remains BLOCKED, the field Gate remains NOT_RUN, C1.16 alias remains device
NOT_VERIFIED, and C1.17 credential failure remains
NOT_REPRODUCED_ON_C1.18.

## Foundation Regression Gate (2026-09-04)

Every future MCP candidate must pass the offline Foundation Regression Gate
before a feature-specific device Gate. The immutable last-known-good MCP
foundation reference is debug-9:
`packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+debug-9+debug-1+debug_iphoneos-arm64e.deb`
(SHA-256 `01732dddd3cbe177e3b02a358a86e87f8ec5c8f9bca1aff6ea629043709c815b`).

The Gate compares that baseline and the candidate before any environment
diagnosis. It audits RootHide linkage and absence of rootful linkage,
SpringBoard filter, HTTP startup and auth source contracts, `mcp-root=4755`,
required/revoked runtime pins, archive ownership, package/control delta, and
target-device maintainer-script syntax. A pre-flight failure is classified as
`FOUNDATION_REGRESSION`; it never invalidates previous Device PASS evidence.
See `diagnostics/test52-c1/foundation_gate.py`,
`test-agent-foundation-regression-gate-unit.py`, and
`docs/DEVICE_TOOL_CAPABILITY_CONTRACT.md`.

Initial host-only validation: Foundation Gate `6/6`, retained C1.8 startup
audit `6/6`, retained C1.9 auth-provisioning audit `5/5`, and complete offline
Host regression `71/71` PASS. No package was built, installed, or deployed;
no device was contacted and `DEVICE_ACTION_COUNT=0`. This adds guardrails only:
TEST-51 remains device `BLOCKED`, TEST-52 remains `NOT_PASS/FAIL_CLOSED`, and
Phase 6 remains `BLOCKED`.

## Authoritative Reading Order

1. `docs/AI_START_HERE.md`
2. `docs/roadmap/PHONEHARNESS_CANONICAL_ROADMAP.md`
3. This file
4. `docs/AI_PROJECT_RULES.md`
5. `docs/TEST_STATUS_MATRIX.md`
6. current `git status --short`
7. only the frozen module evidence and current source relevant to the assigned task
8. historical references only as needed, including `docs/ROADMAP.md` and `docs/NEXT_PHASE_ARCHITECTURE_REVIEW.md`

For TEST-51/52 work, additionally read TEST-51, ADR-065, TEST-52, and ADR-066.
For TEST-53 through TEST-59 runtime work, read the corresponding evidence and
ADR pairs from ADR-067 through ADR-073.
