# PhoneHarness Test Status Matrix

This matrix is a model-agnostic index of evidence already recorded in the
repository. The linked TEST document remains authoritative for exact commands,
counts, exclusions, failures, and device evidence.

Evidence classes are not interchangeable: `HOST_PASS`, `DEVICE_PASS`,
`NOT_TESTED`, `BLOCKED`, `ENVIRONMENT_ISSUE`, `FAIL`, and `N/A` retain their
documented meanings. No fresh applicable evidence means no new PASS.

## Frozen Current Status

- Latest completed functional Gate: TEST-59 `HOST_PASS`.
- Latest governed execution DEVICE_PASS gates: TEST-49 and TEST-50, each with
  narrow documented scope.
- TEST-51: host/E2E complete; device action Gate `BLOCKED`.
- TEST-52: `NOT_PASS` / `FAIL_CLOSED`.
- XCTest Observation Provider: `DEVICE_PASS` only for its narrow read-only
  snapshot-observation scope; it grants no INPUT_TEXT/SUBMIT authority.
- TEST-53 through TEST-59: `HOST_PASS`, `DEVICE_RESULT=NOT_RUN`.

## Evidence Index

| TEST | Title | Evidence status | Proven | Not proven / notes | Source |
| --- | --- | --- | --- | --- | --- |
| 11 | Dynamic Planner | `DEVICE_PASS` | One real browser search plan executed and verified after bounded observation polling. | Broad cross-app planning and later policy layers. | `docs/TEST-11-DYNAMIC-PLANNER.md` |
| 12 | Dynamic Tool Selection | `DEVICE_PASS` | Live advertised-tool selection under an allow-listed policy. | Arbitrary tools or direct Planner execution authority. | `docs/TEST-12-DYNAMIC-TOOL-SELECTION.md` |
| 13 | Goal Decomposition | `DEVICE_PASS` | Bounded sequential read-only decomposition with fresh observations. | Interactive/high-risk decomposition. | `docs/TEST-13-GOAL-DECOMPOSITION.md` |
| 14 | Memory System | `DEVICE_PASS` | Privacy-minimized local metadata persistence and reload after read-only observation. | Planner influence, semantic retrieval, or raw history storage. | `docs/TEST-14-MEMORY-SYSTEM.md` |
| 15 | Skill Registry | `DEVICE_PASS` | Declarative Skill constrains a live tool route. | Skill execution authority or app-specific automation. | `docs/TEST-15-SKILL-REGISTRY.md` |
| 16 | Risk Controller | `DEVICE_PASS` | Pre-execution risk gate on a bounded live contract. | Broad/high-risk autonomous approval. | `docs/TEST-16-RISK-CONTROLLER.md` |
| 17 | Long Running Task | `DEVICE_PASS` | Owner-bound, read-only checkpoints, pause/resume/cancel, and restart interruption marker. | Production scheduler, interactive replay, physical reboot durability. | `docs/TEST-17-LONG-RUNNING-TASK.md` |
| 18 | Task Coordinator | `DEVICE_PASS`, focused read-only | Goal-level read-only coordination, pause/resume, interruption and BLOCKED separation. | Interactive/high-risk coordination, background scheduler. | `docs/TEST-18-TASK-COORDINATOR.md` |
| 19 | Skill Registry Formalization | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Versioned declarative Skill validation and one focused generic live path. | Skill as Executor or app hard-coding. | `docs/TEST-19-SKILL-REGISTRY-FORMALIZATION.md` |
| 20 | Memory Layer | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Task/Skill/Environment summary boundaries after one verified read-only task. | Decision-changing memory or raw history database. | `docs/TEST-20-MEMORY-LAYER.md` |
| 21 | Observation Intelligence | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | AX-first provider routing and unified read-only observation. | Action authority or Vision device execution. | `docs/TEST-21-OBSERVATION-INTELLIGENCE.md` |
| 22 | Vision/OCR Observation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | AX priority and bounded OCR fallback on device. | VLM and broad visual understanding. | `docs/TEST-22-VISION-OCR-OBSERVATION.md` |
| 23 | Semantic Observation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Safe AX-backed semantic page summary. | Planner/action authority or raw observation persistence. | `docs/TEST-23-SEMANTIC-OBSERVATION.md` |
| 24 | Semantic Planner Integration | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Goal -> AX observation -> privacy-safe Planner context. | Device action or arbitrary raw AX/OCR input to Planner. | `docs/TEST-24-SEMANTIC-PLANNER-INTEGRATION.md` |
| 25 | Semantic Execution Prototype | `STATIC_PASS`, `REGRESSION_PASS`; device `NOT_TESTED` | Original host closed-loop prototype and fail-closed preconditions. | Interactive device loop did not pass. TEST-51 supersedes execution governance. | `docs/TEST-25-SEMANTIC-EXECUTION-CLOSED-LOOP.md` |
| 26 | Capability Intelligence | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Trusted, non-executing capability candidate generation with one read-only device input. | Solution choice or execution. | `docs/TEST-26-CAPABILITY-INTELLIGENCE.md` |
| 27 | Solution Evaluation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Transparent advisory ranking from declarative candidates. | Planner replacement or device action. | `docs/TEST-27-SOLUTION-EVALUATION.md` |
| 28 | Personal Intelligence Core | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Confirmed preference/habit/evidence metadata and advisory context. | Automatic policy change or raw personal content storage. | `docs/TEST-28-PERSONAL-INTELLIGENCE-CORE.md` |
| 29 | Semantic UI Graph | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | AX-backed, read-only semantic UI graph with confidence. | GUI-agent execution or raw UI persistence. | `docs/TEST-29-SEMANTIC-UI-GRAPH.md` |
| 30 | Adaptive Intelligence Router | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Advisory source recommendation using sanitized metadata and one read-only observation. | Local/cloud model invocation or Planner authority. | `docs/TEST-30-ADAPTIVE-INTELLIGENCE-ROUTER.md` |
| 31 | Human Teaching Layer | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Explicit teaching intent, confirmation, and validated metadata candidate after one read-only observation. | Real teaching UI or capability activation. | `docs/TEST-31-HUMAN-TEACHING-LAYER.md` |
| 32 | Capability Graduation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Candidate lifecycle/trust metadata and explicit confirmation boundaries. | Automatic Skill/Shortcut/Workflow creation or execution. | `docs/TEST-32-CAPABILITY-GRADUATION-ENGINE.md` |
| 33 | Personal Knowledge Foundation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Owner-controlled private artifact/profile foundation and governed metadata. | Generic retrieval, cloud analysis, or execution. | `docs/TEST-33-PERSONAL-KNOWLEDGE-FOUNDATION.md` |
| 34 | Knowledge Understanding | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Deterministic semantic Rate/Schedule/Customer/SOP entities with provenance. | Generic RAG/vector DB/cloud understanding. | `docs/TEST-34-KNOWLEDGE-UNDERSTANDING.md` |
| 35 | Knowledge Retrieval & Context | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Deterministic query, provenance, alias, validity/version and clarification contracts. | Large production dataset and execution. | `docs/TEST-35-KNOWLEDGE-RETRIEVAL-CONTEXT.md` |
| 35.6 | Knowledge Intelligence Validation | `STATIC_PASS`, `REGRESSION_PASS`; device `N/A` | Domain-agnostic validation framework. | Real version-data Stage 2 was `BLOCKED_ON_REAL_VERSION_DATA`; full unknown-domain E2E `NOT_TESTED`. | `docs/TEST-35.6-KNOWLEDGE-INTELLIGENCE-VALIDATION.md` |
| 36 | Identity & Consent Foundation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Identity/ownership/consent/versioned permission resolution and revocation. | UI, cloud sync, or multi-user authorization. | `docs/TEST-36-IDENTITY-CONSENT-FOUNDATION.md` |
| 37 | Knowledge Lifecycle | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Version chains, valid/knowledge time, conflicts, forgetting and references. | New database/RAG/parser/execution. | `docs/TEST-37-KNOWLEDGE-LIFECYCLE.md` |
| 38 | Active Context | `HOST_PASS`; device `NOT_TESTED` | Private bounded context metadata, lifecycle, snapshots, isolation and fail-closed resume. | Swift UI/client access and device behavior. | `docs/TEST-38-ACTIVE-CONTEXT.md` |
| 39 | Experience & Preference Learning | `HOST_PASS`; device `NOT_TESTED` | Preference, behavior-pattern and procedure-candidate advisory lifecycles. | Automatic learning, execution or UI. | `docs/TEST-39-EXPERIENCE-PREFERENCE.md` |
| 40.0 | Runtime Hardening | `HOST_PASS`; device `NOT_TESTED` | Executor-only action port, private writer and redacted trace boundaries. | UI, voice, cloud or new device behavior. | `docs/TEST-40-RUNTIME-HARDENING.md` |
| 40.1 | Visual Intelligence Foundation | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | Read-only AX-backed visual semantic candidate and safe low-confidence behavior. | Visual execution, demonstration capture or UI. | `docs/TEST-40.1-VISUAL-INTELLIGENCE-FOUNDATION.md` |
| 40.3 | Capability/Skill/Shortcut/App Intent Contracts | Implemented; later host regression covers contract; device `N/A` | Declarative capability methods, metadata-only Shortcut/App Intent and Skill governance. | Actual Shortcut/App Intent invocation or external Skill execution. | `docs/TEST-40.3-GOVERNED-CAPABILITY-SKILL-INTELLIGENCE.md` |
| 41 | Intelligence Orchestration | `HOST_PASS`; device `N/A` | Advisory capability/Skill/method/intelligence-source recommendation. | Model call, Scheduler, Shortcut/App Intent execution. | `docs/TEST-41-INTELLIGENCE-ORCHESTRATION-LAYER.md` |
| 42.1 | Native Capability Bridge | `STATIC_PASS`, `REGRESSION_PASS`, `DEVICE_PASS` | One Apple Maps legacy-link dispatch and Maps foreground observation. | Route calculation, navigation completion or other adapters. | `docs/TEST-42.1-NATIVE-CAPABILITY-BRIDGE.md` |
| 43 | Cognitive Intelligence | `HOST_PASS`; device `N/A` | Deterministic concept graph, advisory discovery/composition and governed experience signals. | LLM inference, persistent graph, automatic Skill or action. | `docs/TEST-43-COGNITIVE-INTELLIGENCE-LAYER.md` |
| 44.1 | Screenshot Session Foundation | `HOST_PASS`; device `N/A` | Temporary privacy-safe visual session contract. | Capture, OCR, translation or UI. | `docs/TEST-44.1-SCREENSHOT-SESSION-FOUNDATION.md` |
| 44.2 | Personal Language Intelligence | `HOST_PASS`; device `NOT_TESTED` | Confirmed, privacy-bounded language learning metadata. | Live capture/OCR, learning UI or model invocation. | `docs/TEST-44.2-PERSONAL-LANGUAGE-INTELLIGENCE.md` |
| 44.3 | Local Visual Understanding | `HOST_PASS`, `E2E_PASS`, `DEVICE_PASS` | Local Vision/OCR temporary session, measured latency/memory, no persistence, `NEEDS_CONFIRMATION`. | Full controlled device corpus cases listed in its `NOT_TESTED` section. | `docs/TEST-44.3-LOCAL-VISUAL-UNDERSTANDING.md` |
| 44.4 | Visual Intent Advisory | `HOST_PASS`, `DEVICE_PASS` | Untrusted visual content yields only confirmable, non-executable advisory. | Confirmation UI or resulting execution. | `docs/TEST-44.4-VISUAL-INTENT-ADVISORY.md` |
| 45 | Action Obligation Ledger | `HOST_PASS`; device `NOT_RUN` | Monotonic action lifecycle and no blind replay after unknown side effect. | Device route change. | `docs/TEST-45-ACTION-OBLIGATION-LEDGER.md` |
| 46 | Task Progress & Recovery | `HOST_PASS`; device `NOT_RUN` | Progress/stall detection and fresh-observe/replan/re-risk recovery contract. | Device behavior or Scheduler. | `docs/TEST-46-TASK-PROGRESS-AND-RECOVERY.md` |
| 47 | Capability Method Health | `HOST_PASS`; device `NOT_RUN` | Privacy-safe attributable aggregate method health and selection input. | Persistent method analytics or new execution method. | `docs/TEST-47-CAPABILITY-METHOD-HEALTH.md` |
| 48 | Provider Architecture Review | Architecture/static `PASS`; regression/device `NOT_RUN` | Observation/Execution/Intelligence provider separation and research decision. | Provider implementation, Frida POC or device route. | `docs/TEST-48-PROVIDER-ARCHITECTURE-REVIEW.md` |
| 49 | Governed Installed-App Launch | `HOST_PASS`, `E2E_PASS`, `DEVICE_PASS` | One uniquely resolved installed app launched through Planner/Risk/Executor/Ledger/Verifier. | Arbitrary app control or in-app work. | `docs/TEST-49-GOVERNED-INSTALLED-APP-LAUNCH.md` |
| 50 | Public Destination Maps Handoff | `HOST_PASS`, `E2E_PASS`, `DEVICE_PASS` | One explicit public destination handed to Maps with one action and fresh foreground verification. | Route correctness, directions, arrival or private locations. | `docs/TEST-50-GOVERNED-PUBLIC-DESTINATION-MAPS-HANDOFF.md` |
| 51 | Semantic Search Modernization | `HOST_PASS`; device Gate `BLOCKED` | Separate focus/input/submit obligations, no-replay recovery and stronger host verifier. | Device search submission; `device_action_count=0` at blocked Gate. Supersedes TEST-25 execution governance. | `docs/TEST-51-SEMANTIC-SEARCH-CLOSED-LOOP.md` |
| 52 | AX Semantic Field Observability | `NOT_PASS` / `FAIL_CLOSED` | Narrow XCTest Provider `DEVICE_PASS` for direct read-only snapshot properties and structure. | Editable=true, secure=false, authorization visibility, Safari field identity; no input authorization. | `docs/TEST-52-AX-SEMANTIC-FIELD-OBSERVABILITY.md` |
| 53 | Dynamic Planner / Agent Brain V1 | `HOST_PASS`; device `NOT_RUN` | Typed capability-first plans, validation, method health, verifier and bounded replan contracts. | Model quality or device execution. | `docs/TEST-53-DYNAMIC-PLANNER-AGENT-BRAIN-V1.md` |
| 54 | Dynamic Plan Runtime Integration | `HOST_PASS`; device `NOT_RUN` | Validated Plan enters existing TaskCoordinator/Risk/Observation/Verifier path. | Real device dynamic-plan execution. | `docs/TEST-54-DYNAMIC-PLAN-RUNTIME-INTEGRATION.md` |
| 55 | Governed Capability Adapter Binding | `HOST_PASS`; device `NOT_RUN` | Typed compiled-step binding to existing adapters, PlanExecutor, Ledger and Verifier. | New device route; TEST-49/50 semantics unchanged. | `docs/TEST-55-GOVERNED-CAPABILITY-ADAPTER-BINDING.md` |
| 56 | Restart-Safe Dynamic Plan Recovery | `HOST_PASS`; device `NOT_RUN` | Reconstruction, rebind, fresh governance, no duplicate verified work, unknown outcome no replay. | Physical reboot/power-loss durability. | `docs/TEST-56-RESTART-SAFE-DYNAMIC-PLAN-RECOVERY.md` |
| 57 | Process Durability & Recovery Ownership | `HOST_PASS`; device `NOT_RUN` | Real subprocess exit/SIGTERM/SIGKILL, concurrent ownership, fencing and fault injection. | Physical power-loss durability remains `NOT_TESTED`. | `docs/TEST-57-PROCESS-DURABILITY-RECOVERY-OWNERSHIP.md` |
| 58 | Recovery Retention & Store-Ledger Consistency | `HOST_PASS`; device `NOT_RUN` | Conservative reconciliation, orphan handling, idempotent cleanup and unknown-outcome retention. | Automatic cleanup scheduling or device behavior. | `docs/TEST-58-RECOVERY-RETENTION-STORE-LEDGER-CONSISTENCY.md` |
| 59 | Governed Task Lifecycle & Terminal Acknowledgement | `HOST_PASS`; device `NOT_RUN` | Terminal truth from Ledger/Verifier/revision/recovery, separate acknowledgement and safe cleanup eligibility. | User-facing acknowledgement UI, background cleanup, physical power loss. | `docs/TEST-59-GOVERNED-TASK-LIFECYCLE-TERMINAL-ACKNOWLEDGEMENT.md` |

## Tests Without Canonical TEST Documents

This repository contains historical MCP/AX/tap/input/retry/self-repair and
build/device evidence outside the numbered TEST-11 through TEST-59 documents.
This matrix does not invent missing TEST IDs or broaden those historical
claims. Consult the relevant source, package/build evidence, device evidence,
and current Master Handoff before relying on them.

## ZCode Stabilization Batches (2026-08-29) — No TEST Status Changes

The ZCode tenure ran Foundation Stabilization work as **Batch Gates (1A-1E),
which are not TEST-xx gates and confer no TEST status**. This matrix is
unchanged by them; every status above remains exactly as documented. For the
avoidance of doubt:

- Batch 1A/1B/1C fixes (replan replay, ledger rotation, device token auth,
  ldid validator, upload hardening, input_text contract honesty) passed their
  batch gates and offline regressions (59/60/61/62 files) — these are
  stabilization evidence, not TEST Passes.
- The input_text root-cause experiments (Batch 1D A/B routing, E0/E1/E2,
  keyboard switch) and the input-method-independent strategy experiments
  (Batch 1E S2/S4) are recorded investigation evidence with raw JSON under
  `_zcode_workspace/diagnostics/`; they are NOT device gates and prove no
  TEST.
- The Batch 1E Phase 5 host-side `InputTextOrchestrator` has offline unit
  evidence only (13/13); its real-device Gate (Phase 6) has NOT run, so no
  device claim of any kind exists for it.
- TEST-51 stays device Gate `BLOCKED`; TEST-52 stays `NOT_PASS`/`FAIL_CLOSED`;
  TEST-60 stays NOT_STARTED. All prior DEVICE_PASS claims remain unchanged.

## Supersession Rules

- TEST-51 modernizes and supersedes TEST-25 execution governance while
  preserving TEST-25 as historical prototype evidence.
- TEST-52 does not supersede TEST-51; it is the missing observability/
  authorization Gate that currently blocks TEST-51 device execution.
- TEST-53 through TEST-59 extend one runtime architecture and do not invalidate
  TEST-49/50 DEVICE_PASS routes.
- A later regression result does not retroactively convert a host-only or N/A
  Gate into DEVICE_PASS.
