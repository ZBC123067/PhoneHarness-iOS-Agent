# PhoneHarness Canonical Roadmap

Status: **AUTHORITATIVE / ROADMAP LOCKED**
Effective date: **2026-09-27**
Scope: Current module status, future module order, development gates, and
roadmap registries.

This is the single authoritative roadmap/status document for future
PhoneHarness development. It does not replace or rewrite frozen evidence.

## Evidence Precedence

When records disagree, apply this order:

1. newer verified real-device evidence;
2. newer frozen module evidence;
3. this canonical roadmap;
4. current source inspection;
5. historical blueprint, handoff, or research;
6. third-party reference.

Frozen module evidence remains historical truth for the gate it froze. A later
roadmap may schedule new work, but cannot rewrite a past frozen result.

## Current Status

| Module | Status |
| --- | --- |
| S2-M3 Authority Cutover | `FROZEN_PROVEN` |
| S2-M4 State & Recovery Skeleton | `FINAL_ACCEPTED` |
| S2-M5 Capability Metadata Registry | `FINAL_ACCEPTED` |
| S2-M6 Second Governed Capability | `FROZEN_PROVEN` |
| S2-M7 Stage 2 Convergence | `FROZEN_PROVEN` |
| S3-M0 Context / Artifact Contract | `FROZEN_PROVEN` |
| S3-M1 Artifact / Receipt / Trace Store | `FROZEN_PROVEN` |
| S3-M2 Async Task | `FROZEN_PROVEN` |
| S3-M3 Session + Runtime Supervisor | `FROZEN_PROVEN` |
| S3-M4 Uncertain Outcome | `FROZEN_PROVEN` |
| S3-M5 Bounded Retry + ExecutionLoopDetector | `FROZEN_PROVEN` |
| S3-M6 Provider Health / Fallback | `FROZEN_PROVEN` |
| S3-M7 Replan / Ask User / Credential Broker | `FROZEN_PROVEN` |
| S3-M8 Checkpoint / Resume | `FROZEN_PROVEN` |
| S3-M9 Governed Multi-Step | `FROZEN_PROVEN` |
| S4-M0 Observation Snapshot / Epoch / Freshness | `FROZEN_PROVEN` |
| S4-M1 Semantic UI | `FROZEN_PROVEN` |
| S4-M2 OCR / Vision | `FROZEN_PROVEN` |
| S4-M3 Screenshot Intelligence Core + Smart Screenshot Backend | `FROZEN_PROVEN` |
| S4-M4 Clipboard / Text / App / System | `FROZEN_PROVEN` |
| S4-M5 File / Log / Crash Intelligence | `FROZEN_PROVEN` |

S2-M6 proved `capability.maps.open_native_link.v1`; blocking debt is `0`.

`STAGE_2_STATUS = FROZEN_PROVEN`

`STAGE_3_STATUS = FROZEN_PROVEN`

`CURRENT_NEXT_MODULE = S4-M6 Process / Service`

### Current S4-M6 completion boundary

The verified S4-M6 sequence is complete through A3-R2:

```text
CURRENT_COMPLETED = S4-M6-A3-R2
CURRENT_NEXT = S4-M6-A3-R3
CURRENT_NEXT_STATUS = PLANNED / NOT_EXECUTED
```

S4-M6-A3-R2 is the latest accepted provider-fusion and direct-libproc
read-only proof. A3-R3 is reserved for the next revalidation step and is not
represented as implemented or passing here.

S2-M7 completed the Stage-2 convergence, protocol-neutral external-frontend
compatibility audit, and aggregate freeze. S3-M0 established and froze the
PhoneHarness-native context/artifact contract surface. S3-M1 established and
froze the Host Artifact, Receipt, and Trace Store foundation. S3-M2 established
and froze the Host async task lifecycle, structured ownership, cooperative
cancellation, deadline, and stale-result suppression foundation. S3-M5
established and froze the bounded, evidence-gated retry-policy and
execution-loop detection foundation without wiring automatic device retries.
S3-M7 established and froze typed replanning, durable user-intervention,
opaque credential-broker, and secure-UI stop/wait contracts without changing
production device execution behavior. S3-M9 established and froze bounded,
deterministic governed multi-step execution with independent governance for
every mutation and completed Stage-3 convergence. The core runtime is
frontend-agnostic; a formal external protocol adapter remains later roadmap
scope and cannot create or bypass action authority.

S4-M4 established and froze the typed Clipboard, Text, App, URL/Resource, and
System capability contracts. Its Host contracts, clipboard metadata proof,
governed app launch, URL handoff, and fresh post-open observation are proven.
S4-M5 established and froze the typed File, Log, and Crash evidence
foundation over the existing bounded device providers, with fail-closed path
validation, privacy redaction, digest-based identity and freshness
composition into S4-M0, non-causal incident classification, and bounded
diagnostic correlation referencing Stage-3 artifacts. Real-device proofs
cover the canonical MCP bounded file read, live unified-log capture through
mcp-logreader, CrashReporter discovery, and real iOS 17 `.ips` parsing.
The separate `TEXT_INPUT_REAL_DEVICE_COMPAT_GATE` remains `OPEN_DEFERRED`:
device text-entry end to end is not proven because neither accepted device
attempt established a deterministic editable semantic target. This is not
evidence of an input-provider defect and does not permit a raw input bypass.

## Pre-Implementation Gates

Every substantive planned module or capability must complete and record all of
the following before implementation:

1. `CANONICAL_ROADMAP_CHECK`
2. `FROZEN_DEPENDENCY_CHECK`
3. `LATEST_REFERENCE_HARVEST`
4. `OFFICIAL_DOCS_CHECKED`
5. `GITHUB_UPSTREAM_CHECKED`
6. `RECENT_RESEARCH_CHECKED`
7. `COMMUNITY_SIGNAL_CHECKED`
8. `LICENSE_COMPATIBILITY_CHECK`
9. `TARGET_DEVICE_COMPATIBILITY_REVIEW`
10. `EXISTING_PHONEHARNESS_FOUNDATION_REVIEWED`
11. `BETTER_CURRENT_SOLUTION_FOUND`
12. `DESIGN_DECISION`
13. `CODEX_REPO_AUDIT`
14. `READY_FOR_IMPLEMENTATION`

Reference research must be refreshed at implementation time. Historical
research is useful input, but is not freshness proof. Small mechanical fixes
may use proportionate research; substantive planned modules and capabilities
may not bypass this gate.

The reference sequence is:

`official specification -> upstream source -> RootHide/jailbreak implementation
when relevant -> mature automation/test framework -> Agent/MCP reference when
relevant -> source/license/compatibility audit -> reuse/adapt/reference-only/
reject -> minimal device gate where necessary -> production implementation`.

This process is the hard `IMPLEMENTATION_FRESHNESS_GATE` for every future
module or substantive subphase. Implementations classify new evidence as
`KEEP`, `ADOPT`, `ADAPT`, `MERGE`, `DEFER`, or `REJECT`; code starts only after
the gate passes. Novelty alone is not an architecture reason.

## Personal Agent OS North Star

PhoneHarness is roadmap-bound as a **local-preference Personal Agent OS**, not
merely an AI that operates an iPhone. The Personal Agent OS composes the
existing PhoneHarness runtime; it does not create a second Planner, authority
system, binding system, Executor, Verifier, Ledger, Runtime Supervisor, retry
engine, recovery runtime, checkpoint system, memory database, provider
registry, trace system, event truth, or Agent Brain.

The canonical product flow is:

`User -> Personal Agent OS -> Personal Control Plane -> Goals / World Model /
Memory / Events -> Specialist Intelligence -> Adaptive Intelligence Router ->
Background Preparation -> Prepared Execution -> Execution Strategy Router ->
Ready To Execute -> Temporary Foreground Lease -> Fresh Observation / Rebind ->
PhoneHarness Governed Runtime -> Observe / Authorize / Bind / Act / Observe /
Verify -> Event / Artifact / Experience / Reflection -> Memory / Goal / Idea /
Skill`.

PhoneHarness device runtime remains the governed **Hands + Eyes**. The Personal
Agent OS is the future coordinating brain, assembled from the existing module
owners rather than implemented as a new monolith.

### Canonical Product Principles

1. `BACKGROUND_FIRST / FOREGROUND_MINIMAL`.
2. `PREPARED_PLAN != EXECUTABLE_PLAN`.
3. Fresh observation is required before device-dependent execution.
4. The user owns the foreground; AI foreground control is temporary and
   preemptible.
5. UI automation is one execution provider, not the whole system.
6. Local is a preference, not a quality-sacrificing dogma; free resources are
   preferred when suitable, and paid resources require user policy/budget.
7. Persistent state belongs to Goals, Projects, Tasks, Artifacts, and Runtime,
   not only chat.
8. Specialist agents share one coherent Personal World Model and governed
   runtime.
9. Proactivity must pass attention policy; human attention is a budget.
10. Artifacts are long-lived product objects.
11. Learning and skill promotion require verified outcomes and controlled
    evidence gates.
12. State/postcondition equivalence outranks exact trajectory equivalence when
    authority, verification, and safety remain satisfied.
13. Deterministic verified paths should replace repeated reasoning when safe.
14. MCP is a capability/execution protocol, not the PhoneHarness brain.
15. `P21 — AI-NATIVE SYSTEM UNITY` (permanent, see below): every capability
    must be composable by the shared AI runtime; no intelligence islands.

### Goal, Plan, Background, And Foreground Contract

The durable identity model is `Mission? -> Goal -> Project? -> Task -> Step ->
Action`. A Plan is a versioned, replaceable, replannable artifact attached to a
Goal, Project, or Task; it is not a permanent identity layer. Replanning may
replace a Plan without replacing Goal identity.

Background preparation may research, reason, plan, discover capabilities,
evaluate providers/costs, compile workflows, and prepare artifacts while the
user continues using the device. A prepared Plan, old `ObservationRef`, old
`ObservedTargetRef`, coordinate, binding, or actionability assumption is only
historical preparation evidence. Before a device-dependent step executes, the
runtime must obtain current observation evidence and rebind/revalidate through
the frozen governance path.

Foreground use follows a future lease lifecycle:
`BACKGROUND_PREPARING -> READY_TO_EXECUTE -> WAITING_FOR_FOREGROUND ->
LEASE_GRANTED -> FRESH_OBSERVE -> REBIND / VALIDATE -> EXECUTE -> VERIFY ->
LEASE_RELEASED`. Human input may preempt it; preemption releases foreground and
invalidates affected UI context before any later reconcile/resume. S4 owns the
observation/invalidation primitives, S5-M10/M11 own scheduling and attention
policy, and S6 owns the product experience. No Foreground Lease scheduler is
implemented by S4-M0.

### Personal Control Plane Boundaries

The Personal Control Plane is a composed view over Goals, Projects, Tasks,
World State, Memory, Events, Agents, Models, Skills, Capabilities, Budgets,
Artifacts, Attention, and History. Its expected owners are S5-M0, S5-M1,
S5-M3, S5-M10, and S5-M11. It is not a new numbered module or god-object.

Persistent specialist agents are reserved for durable specialized reasoning or
work ownership. Skills are reusable capability contracts, Workflows are
structured procedures, and Background Jobs are bounded work. All share one
world model, Goal model, verified Memory, Artifact system, and authority path.

### P21 — AI-Native System Unity (Permanent Development Rule)

Status: **PERMANENT / ALL MODULES**. Effective from S4-M6 onward. Established
by explicit user direction; this roadmap is its authoritative statement.

PhoneHarness is NOT "AI + independent feature modules". PhoneHarness IS ONE
AI-native operating layer whose capabilities behave as parts of one body.
Every current and future capability (UI, apps, text, clipboard, screenshot,
translation, voice, files, logs, crashes, processes, services, shell,
packages, repositories, software management, memory, knowledge, automation,
world model, specialists, and all future capabilities) must be composable by
the shared AI runtime. 任何功能或模块都不得形成独立的智能孤岛。

`AI_NATIVE_CAPABILITY_FABRIC_V1` is the mandatory cross-cutting contract that
carries P21. It is NOT a new runtime, stage, module, agent, planner, memory
system, world model, or authority model. Every capability should be able to
participate in: OBSERVE → UNDERSTAND → RELATE → DISCOVER CAPABILITY →
AUTHORIZE → ACT → OBSERVE AGAIN → VERIFY → LEARN, where applicable.

Permanent one-body invariants:

- `ONE_PERCEPTION_ARCHITECTURE = YES`
- `ONE_WORLD_MODEL_ARCHITECTURE = YES`
- `ONE_MEMORY_ARCHITECTURE = YES`
- `ONE_CAPABILITY_FABRIC = YES`
- `ONE_AUTHORITY_MODEL = YES`
- `ONE_VERIFICATION_MODEL = YES`
- `SECOND_FEATURE_SPECIFIC_AI_RUNTIME_ALLOWED = NO`
- `SECOND_FEATURE_SPECIFIC_WORLD_MODEL_ALLOWED = NO`
- `SECOND_FEATURE_SPECIFIC_MEMORY_SYSTEM_ALLOWED = NO`
- `INTELLIGENCE_ISLAND_ALLOWED = NO`

AI is not a button: a capability should naturally carry AI-readable context
and participate in shared task state; intelligence is systemic, not
cosmetically attached, and no UI is required to display the word "AI".
Modules expose typed semantics; shared Stage-5 intelligence reasons over
them (`MODULE_LOCAL_LLM_REQUIRED = NO` unless an explicitly approved
architecture later proves a local model is a provider implementation
detail). Evidence composes across modules where relevant (Process ↔ Log ↔
Crash ↔ App; Screenshot ↔ OCR ↔ Translation ↔ Annotation; Voice ↔ Text ↔
Personal Language Model; Package ↔ Process ↔ Crash ↔ Recent Change) without
forcing unrelated composition.

Learning is evidence-controlled: one observation never becomes a permanent
rule, one translation never becomes permanent terminology, one crash never
becomes permanent root cause, one process spike never becomes permanent
diagnosis. Current task context is not long-term memory; raw
screenshots/logs/crash reports/process snapshots do not enter permanent
memory merely because AI observed them. Action continuity preserves the same
task/context across capabilities but never bypasses freshness, privacy,
authorization, or verification. `FOCUS_OBJECT_IS_AUTHORIZATION = NO` and
`FOCUS_OBJECT_IS_EXECUTABLE_TARGET = NO` until governed target binding and
fresh revalidation succeed.

### P21 Freeze Gate (Mandatory From S4-M6)

From S4-M6 onward, every module Final Closeout / Freeze must report
`AI_NATIVE_INTEGRATION = PASS/FAIL` with: TYPED_OBSERVATION_AVAILABLE,
SEMANTIC_CONTEXT_AVAILABLE, CAPABILITY_DISCOVERABLE_BY_AI,
CAPABILITY_IS_NOT_AUTHORIZATION, WORLD_MODEL_COMPOSABLE,
CROSS_MODULE_COMPOSABLE, POST_ACTION_VERIFIABLE, LEARNING_HOOK_DEFINED
(each YES/NO/NOT_APPLICABLE — no fake applicability), SECOND_AI_RUNTIME_ADDED
= NO, SECOND_WORLD_MODEL_ADDED = NO, SECOND_MEMORY_SYSTEM_ADDED = NO, and
INTELLIGENCE_ISLAND_CREATED = NO. A module cannot become `FROZEN_PROVEN` if
`AI_NATIVE_INTEGRATION = FAIL`, `INTELLIGENCE_ISLAND_CREATED = YES`, or an
unjustified duplicate core system is added. Every future A0 audit must
contain an AI-Native Integration Audit covering observation, semantic
meaning, cross-module relationships, capability exposure, authority
boundary, verification route, learning/memory relevance, privacy,
shared-world/context integration, and intelligence-island risk. This
requirement is permanent.

### P22 — Architecture Governance Is Agent-Independent

Status: **PERMANENT / ALL IMPLEMENTATION AGENTS**.

Codex, ZCode, Sequoia, and future coding agents are implementation agents,
not architecture owners. The precedence is `Canonical Architecture > Coding
Agent > Model Preference`. An implementation agent must not reinterpret,
simplify, replace, or rebaseline frozen architecture, and must not invent a
second core system. If a frozen architecture change appears necessary, work
stops with `ARCHITECT_REVIEW_REQUIRED = YES`.

Frozen-integrity incident rule: when a frozen-file diff is detected and the
active task did not explicitly authorize a frozen reopen, stop immediately.
Do not repair, reconstruct, normalize, change tests around the drift, update
frozen hashes, or create a replacement freeze. Every substantive task records
`EXPECTED_WRITE_SET`, `ACTUAL_WRITE_SET`, and `UNAUTHORIZED_WRITE_COUNT`;
acceptance requires the last value to be zero.

### P23 — Shared Semantic Context Fabric

Status: **ROADMAP-BOUND / CROSS-CUTTING / NON-AUTHORITATIVE**.

Capabilities consume and contribute bounded typed context through one shared
semantic fabric where applicable: current app, goal, project, task, focus
object, domain, recent text/audio/screenshot/video frame, terminology,
knowledge, organization knowledge, personal preferences, language-learning
state, confidence, provenance, and freshness. This fabric is descriptive
evidence. It may inform understanding, planning, provider selection, and
verification, but cannot bypass RiskController, governed binding, fresh
validation, or Semantic Verifier.

Forbidden: feature-local world models, feature-local memory systems,
feature-local AI brains, isolated terminology stores, or translator-only
context databases. `SESSION_CONTEXT != LONG_TERM_MEMORY`; ephemeral context
may expire and must not silently become permanent knowledge. Future shared
semantic frames may express `INTENT`, `ACTION`, `OBJECT`, `DEADLINE`,
`REASON`, and `DOMAIN` for reuse across Translator, Smart Screenshot, Live
Media Interpreter, Ask AI, Voice, and planning. This is future typed context,
not an S4-M6 implementation.

### P24 — Perceptually Real-Time Interaction

Status: **PERMANENT PRODUCT QUALITY DIRECTION**.

User-facing real-time capability is `PERCEPTUALLY_REAL_TIME`, not fictional
`ZERO_LATENCY` or `EXACTLY_ONE_SECOND`. Media speech, source transcript,
translation, and relevant UI should feel synchronized without obvious waits,
sentence mismatch, unstable revision thrashing, or cumulative drift. Future
acceptance measures include first-useful-result latency, follow latency,
visual sync, cumulative drift, revision stability, and user-perceived
real-time quality. Numeric service levels require real-device benchmarking.

### P0 Daily AI Learning Trinity

The highest-priority daily experiences are Personal Translator, Smart
Screenshot Studio, and Live Media Interpreter. Live Media Interpreter is a
mode of Personal Translator, not a separate AI runtime. Their primary purpose
is English understanding, English learning, English-video comprehension, and
contextual real-world language learning. Final product acceptance requires
daily-use UX quality, English-learning value, latency/stability, cross-feature
continuity, and real-device daily-use proof; backend tests alone are
insufficient.

`TRANSLATION_PROVIDER != TRANSLATION_INTELLIGENCE`. Apple, local OPUS-class,
cloud, and future models are providers. Shared translation intelligence is:
semantic understanding -> context/domain/terminology/knowledge resolution ->
meaning representation -> provider strategy -> translation -> semantic
refinement -> verification -> output. Personal Translator must never collapse
to `Text -> Translation API`.

The future shared Contextual Terminology Resolver uses domain, sentence,
recent context, app/document/media, knowledge provenance, organization
knowledge, user confirmation, and confidence. Terms such as SI, SWB, OBL,
MBL, HBL, VGM, POL, POD, CY, CFS, DEM, DET, T/S, and BC must not be globally
hardcoded to one meaning. In shipping context SI may mean Shipping
Instruction with preferred rendering 补料; unrelated contexts remain free to
resolve it differently.

The shared future knowledge architecture has four layers: Universal, Domain,
Organization, and Personal Knowledge. Structured ingestion is Document ->
Entity -> Term -> Alias -> Definition -> Domain -> Relationship -> Example ->
Source -> Confidence. Evidence preserves `USER_CONFIRMED`,
`ORGANIZATION_CONFIRMED`, `DOMAIN_KNOWLEDGE`, `CURRENT_CONTEXT_EVIDENCE`,
`AI_INFERENCE`, and `GENERIC_FALLBACK`; one observation never becomes
permanent knowledge.

Latency-sensitive experiences use a Fast Path for perception, cached
terminology, session context, fast/local providers, and immediate UI, plus a
Deep Path for stable reasoning, knowledge retrieval, quality refinement, and
controlled revision. Heavy retrieval/model work is not required for every
partial ASR result, and refinement must not cause unbounded caption thrashing.

Live Media Interpreter's future typed `AudioSegment` binds segment identity,
start/end timestamps, revision, source text, translation, confidence, state,
provider provenance, and freshness. Source and translation reference the same
segment; older revisions cannot overwrite newer ones; stale results are
dropped; rendering is timestamp-locked; cumulative drift is forbidden.
Progression is `PARTIAL -> STABLE_PREFIX -> FINAL`.

The future Adaptive Translation Island presents Chinese translation above
the English transcript for the same AudioSegment, with adaptive height,
rolling sentence window, bounded caption buffer, atomic bilingual publish,
caption trail, replay, Smart Copy, and bookmark actions. Its dimensions remain
a design envelope, not frozen pixel contracts.

Future Audio-Visual Fusion composes audio, video frame, screenshot, AX where
applicable, OCR, Vision, app/domain context, terminology, and knowledge while
preserving original ASR evidence, candidate correction, confidence, and
provenance. It never silently rewrites raw evidence. Future `MediaMoment`
composes frame, AudioSegment, transcript, translation, timestamp, current app,
OCR/Vision context, focus object, annotation graph, and learning context
without duplicate histories or world models.

The English-learning loop is `SEE/HEAR -> UNDERSTAND -> TRANSLATE -> EXPLAIN
-> PRONOUNCE -> SHADOW -> SAVE CANDIDATE -> RE-ENCOUNTER -> VERIFY LEARNING`.
States are `NEW`, `CANDIDATE`, `LEARNING`, `KNOWN`, and `MASTERED`;
`AI_GUESS != USER_CONFIRMED`. Raw audio is not stored long-term by default.
Replay, Voice Coach, shadowing, recent-segment questions, bookmarks, and study
summaries remain future module work.

### Settings Architecture

`ZERO_CONFIGURATION_FIRST = YES`, `CONTEXT_CONTROLS_SECOND = YES`,
`PROGRESSIVE_DISCLOSURE = YES`, and `ONE_SETTINGS_REGISTRY = YES`. The main UI
remains minimal and frequent controls stay contextual. App preferences may
project Appearance & Interaction, Personal Translator, Smart Screenshot, and
Voice & Learning. Advanced iOS Settings projections may cover AI & Models,
Privacy & Memory, Background Intelligence, Audio, Permissions, Automation,
Diagnostics, and Developer settings. Multiple projections share one registry;
duplicate setting stores are forbidden. S4-M6 does not implement Settings UI.

## Stage 3 - Runtime Continuity And Governed Programs

The order below is fixed.

| Module | Canonical scope |
| --- | --- |
| S3-M0 | Context / Artifact Contract; `DecisionEnvelope`; `CandidateRef`; `ActionCandidateSet`; `ObservedTargetRef` schema; Semantic Task Program contract; constrained-generation contract; runtime context projections |
| S3-M1 | Artifact / Receipt / Trace Store; privacy-safe first-class telemetry and trace |
| S3-M2 | Async Task |
| S3-M3 | Session and Runtime Supervisor; Task Capsule; execution continuity; app lifecycle is not Agent Runtime lifecycle; reconcile before resume |
| S3-M4 | Uncertain Outcome |
| S3-M5 | Bounded Retry and `ExecutionLoopDetector`; repetition, stagnation, oscillation, and no-progress detection |
| S3-M6 | Provider Health / Fallback; owned-service recovery policy boundary |
| S3-M7 | Replan / Ask User / Fail Safe; Credential Broker contract; opaque credential handles; `WAITING_FOR_USER_AUTH`; secure UI fail-closed |
| S3-M8 | Checkpoint / Resume |
| S3-M9 | Governed Multi-Step; Semantic Task Program execution |

No additional Stage-3 module is created for these concepts.

## Stage 4 - Device Intelligence And Governed Operations

| Module | Canonical scope |
| --- | --- |
| S4-M0 | Observation Snapshot / Epoch / Freshness; prepared-plan freshness boundary; foreground/user-activity invalidation foundation; execution-time fresh-observation requirement |
| S4-M1 | Semantic UI; `UIObject`; `ObservedTargetRef`; Dynamic Legal Operation Set; `ActionCandidateSet`; `PreDispatchValidation`; semantic target re-resolution; bounded Semantic Wait; state/postcondition-equivalence foundation; ask-about-screen semantics |
| S4-M2 | OCR / Vision; structured-UI-to-OCR-to-Vision escalation; screen-understanding fallback |
| S4-M3 | Screenshot Intelligence Core; Smart Screenshot backend; ROI/region generation; Delta Snapshot optimization; screenshot contribution to Unified Perception |
| S4-M4 | Clipboard / Text / App / System Intelligence; non-UI execution/context foundations |
| S4-M5 | File / Log / Crash Intelligence |
| S4-M6 | Process / Service Intelligence; Process Ownership; Service Capability; owned-service self-healing implementation |
| S4-M7 | Controlled Shell; owned-process enforcement |
| S4-M8 | Package / Repository Intelligence; package-architecture compatibility gate |
| S4-M9 | Software Manager |
| S4-M10 | Shortcut / Semantic Drivers; external-protocol governed adapter foundation |
| S4-M11 | Execution Strategy Router; Constrained / Verified Fast Path; Verified Macro; Best Path Optimizer |
| S4-M12 | Stage 4 Convergence; Unified Perception; state-equivalent recovery; provider-metadata readiness; freshness integration; bounded Semantic Wait |

## Stage 5 - Knowledge, Experience, And Intelligence Policy

| Module | Canonical scope |
| --- | --- |
| S5-M0 | Knowledge / Memory / Goal Contract + Context Controller; Mission/Goal/Project/Task identity; Plan as versioned artifact; memory roles and provenance |
| S5-M1 | Knowledge OS + Personal World Model + Runtime Canonical Truth; Personal Event View; Idea semantics; Personal Wiki backing |
| S5-M2 | Personal Models: preferences, people, work, routines, decisions, and relationship projections |
| S5-M3 | Experience Store + Reflection + Performance Memory; verified success/failure corpus; transition-divergence diagnostics; replay evidence |
| S5-M4 | Skill Registry V2; progressive discovery; on-demand loading; version/integrity/evaluation/compatibility |
| S5-M5 | Human Teaching; semantic teaching rather than coordinate recording |
| S5-M6 | Experience Compiler / Skill Graduation / Skill Evolution; controlled Skill/Workflow/Verified Workflow/Compiled Workflow promotion |
| S5-M7 | Personal Language Intelligence |
| S5-M8 | Communication Intelligence |
| S5-M9 | Technology Radar / Research Agent / Research Worker |
| S5-M10 | Scheduler / Automation Evolution; Background/Idle Intelligence; Opportunity candidate production; Foreground Lease scheduling policy |
| S5-M11 | Context / Confidence / Adaptive Intelligence / Attention / Budget Policy; `AvailableCapabilityView`; progressive discovery; Agent Budget; specialist-agent orchestration; evidence-based Self Model; Quality Floor |

Quality Floor outranks resource optimization. Model calls, cost, latency,
energy, and memory may be optimized only after required quality, safety, and
success constraints are satisfied.

## Stage 6 - Product Experience

| Module | Canonical scope |
| --- | --- |
| S6-M0 | Product Experience Contract + Personal Agent OS Principles |
| S6-M1 | Task Center / Goals / Projects / Activity / Ideas / Live Artifacts / Personal Wiki / Background Work / Ready-to-Execute / Foreground Lease / Settings / Renderer |
| S6-M2 | Local AI / Model Lifecycle + Resource Governor; local-model background-recovery gate |
| S6-M3 | Cloud Provider / Router |
| S6-M4 | Live Voice / Jarvis / Barge-In / interruptible TTS; execution-time interruption; safe pause/cancel/redirect/resume; session continuity |
| S6-M5 | Siri / App Intents / Action Button / Shortcuts / Spotlight / Deep Link |
| S6-M6 | Floating Assistant |
| S6-M7 | Smart Screenshot Workspace; Resizable AI Region UX |
| S6-M8 | Widget / Live Activity / Dynamic Island; structured progress projections |
| S6-M9 | PhoneHarness / ChatGPT / Siri Triple Entry and Cross-Entry Continuity over one governed core runtime |
| S6-M10 | Multi-Channel with shared task continuity |
| S6-M11 | Proactive / Ambient Intelligence UX; Opportunity and Idea surfaces; Attention policy; Daily Brief; background status |
| S6-M12 | External Protocol Adapter surface |
| S6-M13 | Deferred Candidates, including Shadow Competition and future protocol/model/iOS capabilities subject to freshness gates |
| S6-M14 | v1 Reliability Freeze |

The module counts are fixed at 13 Stage-4 modules, 12 Stage-5 modules, and 15
Stage-6 modules. Details belong in bounded subphases; module counts change only
through an explicit dependency-backed architecture proposal.

## Cross-Cutting Contracts

### Credential Broker

Credential Broker is not `RiskController`. Credential possession never creates
Action Authorization. Secrets do not enter model context by default; sensitive
credentials use opaque handles. User authentication remains user-owned. Face
ID, passcode, and financial-authentication bypasses are forbidden.

### Process And Service Ownership

PhoneHarness-owned workers and processes require explicit ownership identity,
bounded cancellation, and lifecycle tracking. Normal cancellation cannot use
generic `killall`. Automatic service restart is limited to PhoneHarness-owned
or explicitly registered owned services. Apple and system daemons are
read-only by default.

### Experience Flywheel

`Verified Device Execution -> Verifier Result -> Success/Failure Corpus ->
Experience Compiler -> Candidate -> Shadow -> Device Gate -> Promote`

One successful run cannot cause autonomous promotion. Self-RL on A17 Pro is
not a near-term core requirement.

### Personal World Model, Memory, And Wiki

The Personal World Model is owned by the existing Knowledge/Personal Model
architecture and may represent users, people, companies, projects, goals,
tasks, devices, documents, places, events, commitments, shipments, apps,
artifacts, and relationships. Memory roles include working, episodic,
semantic, preference, procedural, and experience/failure memory. They are
semantic roles, not mandatory separate databases. Facts preserve provenance,
time, confidence, scope, last-confirmed evidence, and conflicting claims where
appropriate; contradictions are not silently merged.

The Personal Wiki is a user-visible/editable projection of this canonical
world model and Memory, not a second knowledge database. S5-M1 owns its data
semantics and S6-M1 owns its product surface.

### Routing, Budget, And Capability Discovery

The S4-M11 Execution Strategy Router answers **how to act** by selecting the
lowest-variance verified path that meets intent, quality, compatibility,
authority, verification, and reliability, then optimizes latency, cost,
foreground occupancy, and compute. Candidate paths include native/system
capabilities, App Intents, Shortcuts, URL/deep links, local or free APIs, MCP,
proven private interfaces, semantic drivers, verified workflows/macros,
structured UI, OCR, Vision, and foreground GUI automation. It reuses existing
Capability/Provider foundations and does not add a Provider architecture.

The S5-M11 Adaptive Intelligence Router answers **who or what should think**.
Its modes are `AUTO`, `LOCAL_ONLY`, `FREE_ONLY`, `FASTEST`, `BEST_QUALITY`, and
`CUSTOM`. `AUTO` combines local/free preference with quality floor, success
probability, latency, cost, and resource state; it is not always-local. Agent
Budget covers money, time, compute, attention, and foreground time. Paid use
must never occur silently outside explicit user policy.

Capability discovery is progressive: `Intent -> Domain -> Skill -> Capability
-> Provider`. S5-M4 owns the Registry/on-demand skill loading, S5-M11 owns the
projected `AvailableCapabilityView`, and S4 capability/provider metadata is the
source. No second Registry or permanent hard-coded ranking is created.

### Event, Artifact, Learning, And Proactivity Boundaries

Stage-3 Receipt, Trace, Ledger, Checkpoint, and Runtime state remain canonical
low-level execution evidence. Stage 5 may project higher-level domain events
that reference this evidence, but no second event truth store is allowed. Chat
history is not canonical long-running task state.

Artifacts are long-lived product objects. S3 Artifact Store remains the
foundation; S6-M1 renders current state, progress, plans, research, blockers,
decisions, results, and evidence. User-facing progress labels are projections
of canonical state, not a new task state machine.

Verified experience may progress through `Pattern -> Skill Candidate ->
Semantic Workflow -> Shadow/Evaluation -> Verified Workflow -> Promoted Skill
Version -> optional Compiled/Fast Representation`. Skills, Workflows, Macros,
and compiled paths are one controlled model, not competing systems. Human
teaching records semantics rather than coordinates. Reflection and performance
memory consume verified outcomes only and never grant authority.

Background/Idle Intelligence is event-driven and resource-aware. The
Opportunity Engine produces candidates, not authorized actions. Ideas are
first-class durable objects with evidence, related Goal, expected benefit,
confidence, next step, and status. The Attention Manager may ignore, remember,
research, brief, suggest, notify, or interrupt based on importance, urgency,
confidence, actionability, novelty, interruption cost, and user context.

### Perception And Verification Convergence

Stage-4 perception serves ask-about-screen, planning, and GUI execution.
Accessibility/structured UI, screenshot, OCR, Vision, and app context converge
toward provenance-preserving Unified Observation. Conflicts remain explicit.
Delta Snapshot is a token/compute/latency optimization, never correctness
authority, and cannot bypass full refresh under uncertain freshness.

Bounded Semantic Wait observes semantic conditions instead of relying on
fixed sleeps. UI self-healing means fresh observe, semantic target
re-resolution, current legal-operation evaluation, and current governance; it
does not permit blind retry after unknown dispatch. Semantic verification
accepts state/postcondition-equivalent legal outcomes and does not require an
identical trajectory. Semantic Verifier authority remains unchanged.

### MCP And External Protocol Boundary

MCP remains a capability/execution protocol, not application memory or Agent
Brain. Cross-call PhoneHarness state belongs to the PhoneHarness Runtime and
explicit typed handles, not hidden protocol sessions. MCP Tasks and
`input_required`/MRTR concepts are external-adapter references mapped to frozen
Async Task, `WAITING_FOR_USER`, intervention, checkpoint, cancel, resume, and
trace contracts. They are not copied into core. S4-M10 owns adapter
foundations; S6-M12 owns the formal external protocol surface.

### Voice And Entry Continuity

S6-M4 is a hard product requirement: streaming listening and intent,
barge-in, interruptible TTS, execution-time stop/pause/redirect/question/
continue, safe reconcile/replan, and natural continuation in the same Task.
Voice interruption is not Action Authorization and cannot bypass Risk,
binding, unknown-outcome handling, checkpoint/retry policy, or secure UI.

S6-M9 is a hard requirement for PhoneHarness App, ChatGPT App, and Siri to
converge on one PhoneHarness core Runtime with shared logical Task identity,
checkpoint lineage, evidence, intervention state, governance, and permitted
artifact/progress views. Entry is not authority. Siri may transition sustained
interaction into S6-M4 without creating a second runtime.

## Feature Registry

### `feature.smart_screenshot.ai_region_window.v1`

- Status: `BACKEND_FROZEN_PROVEN / UX_ROADMAP_BOUND`
- Backend owner: `S4-M3`
- Backend status: `FROZEN_PROVEN`
- UX owner: `S6-M7`
- UX status: `NOT_IMPLEMENTED`
- New stage required: `NO`
- Second agent created: `NO`
- Backend implementation complete: `YES`
- UX implementation started: `NO`
- Principles: `RECTANGULAR_REGION`, `STRUCTURED_TEXT_FIRST`, `OCR_SECOND`,
  `VISION_FALLBACK`, `SINGLE_ACTIVE_REGION_V1`, `OBSERVATION_BOUND`,
  `REGION_GENERATION_BOUND`, `DROP_STALE_RESULT`, `SESSION_EPHEMERAL`,
  `NO_SECOND_AGENT`, `NO_DIRECT_REGION_TO_MUTATION`,
  `SECURE_UI_FAIL_CLOSED`.

The frozen S4-M3 backend does not constitute implementation of the S6-M7 UX.

### `feature.live_ai_translation_learning.v1`

- PRODUCT_NAME: `Personal Translator`
- CHINESE_NAME: 个人翻译助理
- PRIORITY: `P0`
- Name: Live AI Translation + Vocabulary Learning（实时 AI 翻译与语言学习）
- Status: `ROADMAP_BOUND / NOT_IMPLEMENTED`
- Product binding: Personal Translator is a first-class PhoneHarness product
  capability built on this feature — not an independent runtime. It shares the
  `AI_LENS_INTERACTION_SYSTEM_V1` foundation and the shared AI Action Dock
  defined below.
- New stage required: `NO`
- Current development remains `S4-M4 Clipboard / Text / App / System`; this
  entry changes no module order, changes no `CURRENT_NEXT_MODULE`, and starts
  no implementation.
- Primary language-intelligence owner: `S5-M7` (translation, context/domain
  translation, vocabulary/phrase intelligence, candidate/promotion logic)
- Primary product UX owner: `S6-M7` (movable/resizable floating translation
  region, rolling translation workspace)
- Foundation reuse: `S4-M3` (`FROZEN_PROVEN`: Screenshot Intelligence, ROI,
  RegionGeneration, stale-result suppression) with S4-M0 observation lineage.
- Additional owners: `S5-M1` (Personal World Model representation for
  vocabulary/phrase entities), `S5-M2` (user language proficiency / mastery
  model), `S5-M3` (exposure / experience / verified learning outcomes),
  `S5-M10`/`S5-M11` (background learning analysis, attention policy, when to
  surface suggestions), `S6-M4` (Live Voice: ask meaning, save word,
  interrupt/resume translation), `S6-M8` (optional Live Activity /
  Dynamic Island learning status).
- Product requirements: `MOVABLE_TRANSLATION_REGION`, `RESIZABLE_TRANSLATION_
  REGION`, `FLOATING_TRANSLATION_WINDOW`, `ROLLING_TRANSLATION`,
  `CONTINUOUS_SCROLL_UNDERSTANDING`, `NEW_CONTENT_ONLY_PROCESSING`,
  `STRUCTURED_TEXT_FIRST`, `OCR_SECOND`, `VISION_FALLBACK`,
  `CONTEXT_AWARE_TRANSLATION`, `DOMAIN_AWARE_TRANSLATION`,
  `WORD_FREQUENCY_TRACKING`, `PHRASE_FREQUENCY_TRACKING`,
  `LOOKUP_FREQUENCY_TRACKING`, `AUTOMATIC_VOCABULARY_CANDIDATES`,
  `MANUAL_SAVE_WORD`, `MANUAL_SAVE_PHRASE`, `MASTERY_MODEL`,
  `KNOWN_WORD_SUPPRESSION`, `REAL_CONTEXT_EXAMPLES`,
  `PERSONAL_VOCABULARY_MEMORY`, `BACKGROUND_LEARNING_ANALYSIS`.
- Product modes: `SPOT_TRANSLATE`, `LIVE_LENS`, `LEARNING_MODE`,
  `LIVE_MEDIA_INTERPRETER`, and future `CONVERSATION_MODE`. Live Media
  Interpreter remains a Personal Translator mode and shares the canonical
  perception, semantic-context, provider-strategy, authority, verification,
  and learning systems.
- Rolling-translation behavior (future, not implemented): observe the selected
  region; detect content changes while scrolling; distinguish already-processed
  content from newly appearing content; prioritize structured text; use OCR
  when structured text is insufficient; use Vision only when OCR/structured
  evidence is insufficient; drop stale translation results; preserve
  surrounding context across scrolling where safe; avoid retranslating
  unchanged content.
- Language intelligence (future): current sentence, surrounding and previous
  visible content, application/document context, domain context (e.g.
  shipping/logistics, software development, technical documentation, email,
  news, general English), and user proficiency; prefer domain-appropriate
  meaning over literal word-by-word translation.
- Vocabulary intelligence (future): importance may weigh seen_count,
  recent_seen_count, lookup_count, manual_save, wrong/review history, mastery,
  domain relevance, comprehension blocking, and user known-marking; raw
  frequency alone never promotes vocabulary; high-frequency trivial stopwords
  do not automatically become learning items.
- Memory model (future): Candidate Memory (automatically discovered
  vocabulary candidate) vs Confirmed Memory (manually saved or promoted by
  sufficient repeated evidence), represented through the existing Stage-5
  memory/world-model architecture; fields such as word/phrase, meaning,
  pronunciation, Chinese explanation, real-context example, domain,
  first_seen, last_seen, seen_count, lookup_count, wrong_count, mastery_score,
  manually_saved, and provenance. No automatic permanent memory from a single
  seen word; no second memory database.
- Principles: `NO_SINGLE_SEEN_WORD_PERMANENT_MEMORY`,
  `NO_SECRET_TEXT_TO_LANGUAGE_MEMORY`, `TRANSLATION_RESULT_IS_AUTHORIZATION
  _NO`, `VOCABULARY_MEMORY_IS_AUTHORIZATION_NO`,
  `REGION_COORDINATE_IS_SEMANTIC_IDENTITY_NO`,
  `OCR_VISION_OUTPUT_IS_AUTHORITY_NO`, `DIRECT_REGION_TO_MUTATION_NO`,
  `DIRECT_OCR_VISION_TO_MUTATION_NO`, `DROP_STALE_TRANSLATION_RESULT`,
  `OBSERVATION_EPOCH_IS_REGION_GENERATION_NO`, `NO_SECOND_PERCEPTION_RUNTIME`,
  `NO_SECOND_MEMORY_RUNTIME`, `NO_SECOND_SCHEDULER_RUNTIME`,
  `NO_SECOND_AGENT_RUNTIME`.
- Translation Lens (future UX): movable, resizable, floating; adjustable
  glass strength/transparency with Liquid-Glass-style treatment where
  implementation permits; source remains visually available beneath the Lens;
  semantic region tracking; scroll-aware continuation; pin/follow behavior.
  The Lens primarily identifies the INPUT/FOCUS REGION; main translated
  output must not permanently cover source content.
- `PEEK_ORIGINAL` (future UX): temporarily reveal the original text without
  permanently losing the translated view.
- Smart Copy (future UX): Copy Translation, Copy Original, Copy Bilingual,
  Copy Current Sentence, Copy Visible Translation Region, Copy Region Text,
  Copy Region Image, and Copy With Timestamp where applicable.
- Learning actions (future UX): Read Aloud, Slow Read, Word Playback, Phrase
  Playback, Sentence Playback, Explain, Grammar Explain, Save Phrase, Shadow
  This Sentence, and Ask AI.
- Personal Translator output surfaces (future): Island Translation Stream,
  Expanded Translation Card, Learning Dock, context-aware translation,
  domain-aware translation, Translation Stability Gate, Translation Diff /
  new-content-only processing, stale-result drop. Reuses S4-M0/S4-M1/S4-M2/
  S4-M3/S4-M4 frozen owners; no second perception stack.
- Personal Translator voice (future): `READ_ALOUD`, `SLOW_READ_ALOUD`,
  `WORD_PRONUNCIATION`, `PHRASE_PRONUNCIATION`, `SENTENCE_PRONUNCIATION`,
  `REPEAT_PLAYBACK`, `SHADOWING_MODE`, `USER_SPEECH_CAPTURE`,
  `PRONUNCIATION_FEEDBACK`, `GUIDED_SPEAK_WITH_ME`. Feedback dimensions only
  where provider evidence supports them (word correctness, stress, rhythm,
  pausing, intonation, pronunciation confidence); no unsupported phoneme-level
  precision promises; feedback is never reduced to an unexplained numerical
  score. Primary voice owner: `S6-M4`.
- Personal language memory (future): Candidate Vocabulary != Confirmed
  Vocabulary; mastery states NEW/CANDIDATE/LEARNING/KNOWN/MASTERED; evidence
  dimensions exposure count, lookup count, save count, read-aloud count,
  shadowing count, speech-error history, domain/context, last exposure. One
  observation must not permanently define knowledge state.
- Translation preference (future): `AI_GUESS` / `CANDIDATE` /
  `USER_CONFIRMED`; user-confirmed preference carries the strongest future
  influence; user-specific terminology is never hardcoded as universal truth.
- Personal Translator future enhancements (non-blocking ideas, not
  implemented): Morning Language Brief, My English Progress, Bilingual Peek,
  Why This Translation, Conversation Mode.
- Smart Screenshot interop (future): Smart Screenshot selected text/region/
  annotation may invoke Personal Translator, Read Aloud, Vocabulary, Phrase
  Analysis, Why This Translation, Save to Knowledge; the Translation Lens may
  invoke Freeze/Capture → Smart Screenshot Studio → Markup → Ask AI. OCR,
  Vision, and translation engines are never duplicated.
- Live Media Interpreter (future mode): a provider-neutral
  `SystemAudioProvider` feeds audio perception, VAD, streaming ASR,
  `AudioSegment`, shared semantic context, terminology resolution,
  translation strategy, atomic bilingual captions, and shared learning/Ask
  AI/Screenshot/Voice actions. ReplayKit is one possible provider, not an
  architectural dependency. Replay Last Sentence uses only a bounded
  ephemeral audio ring buffer (approximately 5-15 seconds as a design class),
  and raw audio is not stored long term by default. Learn This Sentence,
  original-speaker replay where technically supported, normal/slow replay,
  Voice Coach handoff, shadowing, recent-segment questions, MediaMoment
  bookmarks, and optional saved-session study summaries remain future owner
  work. This entry adds no runtime in S4-M6.

### `feature.smart_screenshot_studio.v1`

- PRODUCT_NAME: `Smart Screenshot Studio`
- CHINESE_NAME: 智能截图工作台
- PRIORITY: `P0`
- Status: `ROADMAP_BOUND / PARTIAL_FOUNDATION_PROVEN` — S4-M3 Screenshot
  Intelligence Core + Smart Screenshot Backend is `FROZEN_PROVEN` (ROI,
  RegionGeneration, stale-result suppression, memory-only sessions), but the
  full user-facing capture/edit/annotation/Ask-AI UX is NOT implemented.
  This entry must not be read as implying the final Studio already exists.
- New stage required: `NO`; no second perception/freshness/memory/authority/
  scheduler/agent runtime.
- Shared foundation: `AI_LENS_INTERACTION_SYSTEM_V1` (below) — one common
  floating/selection interaction system shared by Personal Translator, Smart
  Screenshot Studio, Ask AI, Extract, and Inspect. No third independent
  user-facing product runtime.
- Focus Object (shared concept): represents what the user is currently
  acting on; conceptual categories TEXT/REGION/SCREENSHOT/ANNOTATION/
  UI_ELEMENT/IMAGE_OR_OBJECT.
  `FOCUS_OBJECT_IS_AUTHORIZATION = NO`;
  `FOCUS_OBJECT_IS_CURRENT_ATTENTION_TARGET = YES`.
- AI Action Dock (shared, AI 功能坞): one shared Dock component used by
  Personal Translator and Smart Screenshot Studio; approximately 6–7 primary
  visible actions when layout space permits, overflow via CHEVRON/MORE; may
  appear below/above/side-attached/floating/inside an expanded card/inside
  compatible island-expanded UX; exact placement is future UX
  implementation.
- Action Dock user ownership (hard requirements): `USER_REORDER_ACTIONS`,
  `USER_PIN_ACTIONS`, `MODE_SPECIFIC_ACTION_LAYOUT`,
  `CONTEXT_ADAPTIVE_RECOMMENDATIONS`, `USER_LAYOUT_PERSISTENCE`;
  `AI_CAN_DISPLACE_USER_PINNED_ACTION = NO`. Ordering priority:
  USER_PINNED > USER_ORDER > CONTEXT_RECOMMENDED > OVERFLOW. User ownership
  outranks AI recommendation.
- Mode-aware Dock (product intent, not static UI): Personal Translator may
  prioritize Read Aloud / Slow Read / Shadowing / Vocabulary / Explain /
  Save / More; Smart Screenshot may prioritize Ask AI / Arrow / Shape /
  Number Marker / Text / Highlight / More; an English-text screenshot may
  combine Ask AI / Translate / Read Aloud / Markup / Number / Vocabulary /
  More. The underlying Dock is ONE shared component.
- Capture requirements (future): arbitrary region selection, move selected
  region, resize from corners and edges, full-screen capture, crop,
  reselect, precise adjustment, future scrolling screenshot capability.
  Capture selection reuses the shared AI Lens / Region interaction
  foundation; no second region-selection runtime.
- Non-destructive editing architecture (future):
  ORIGINAL_SCREENSHOT + EDIT_LAYERS + ANNOTATION_GRAPH +
  OPTIONAL_FLATTENED_EXPORT; editing remains non-destructive internally.
  Hard controls: FREEHAND, LINE, ARROW, RECTANGLE, SQUARE, CIRCLE, ELLIPSE,
  TRIANGLE, TEXT, HIGHLIGHT, BLUR, PIXELATE, NUMBER_MARKER, UNDO, REDO,
  MOVE_ANNOTATION, RESIZE_ANNOTATION, DELETE_ANNOTATION.
- Structured Annotation Graph (future): annotation evidence includes
  annotation id, type, region/geometry, number-marker value, text content,
  style metadata, and relationship to screenshot/region — annotations are
  not only flattened pixels.
  `ANNOTATION_GRAPH_IS_AUTHORIZATION = NO`;
  `ANNOTATION_ID_CAN_BE_AI_REFERENCE = YES` (e.g. "Why is number 2 wrong?"
  references structured Annotation #2 instead of re-inferring from pixels).
- Number markers (future): automatic sequence workflow 1/2/3/…; move,
  resize, delete, optional renumber; circle/square marker style; step-line
  relationship. Final exact visual style is future UX.
- Ask AI (future, first-class action): Screenshot/Region + AX where
  applicable + OCR + Vision + Annotation Graph + Context → AI. Intents:
  Explain, Translate, Extract, Compare, Analyze UI, Analyze error,
  Summarize, Turn into email/text, Identify object, Inspect marked regions.
  No second Agent runtime.
- AI intent markers (future): an annotation/region may optionally carry
  ASK_ABOUT_THIS / TRANSLATE_THIS / EXTRACT_THIS / COMPARE_THIS /
  IGNORE_THIS / FIX_OR_REVIEW_THIS. Intent metadata is descriptive context;
  `ANNOTATION_INTENT_IS_AUTHORIZATION = NO`.
- Privacy (shared hard requirements): `SECURE_UI_TRANSLATION_CAPTURE = NO`,
  `SECRET_TEXT_LANGUAGE_MEMORY = NO`, `PASSWORD_MEMORY = NO`,
  `OTP_MEMORY = NO`, `AUTH_TOKEN_LANGUAGE_MEMORY = NO`,
  `UNCONFIRMED_MEMORY_AUTO_PERMANENT = NO`,
  `SCREENSHOT_SECRET_AUTO_KNOWLEDGE_PERSISTENCE = NO`,
  `RAW_SCREENSHOT_AUTO_LONG_TERM_MEMORY = NO`. Sensitive-data detection may
  recommend blur/pixelate/review but must never silently alter user content.
- Future enhancements (non-blocking ideas, not implemented): Scrolling
  Screenshot, Pin Screenshot, OCR Copy, Magnifier, Color Picker, Pixel
  Distance / Ruler, Auto Border, Background / Shadow, Canvas Expansion,
  Rotate, Quick Export, Screenshot Workspace, multi-screenshot task
  context, Ask-AI conversation history bound to screenshot artifact/context.
- Product acceptance contract (future): PERSONAL_TRANSLATOR_P0_BOUND = YES;
  SMART_SCREENSHOT_STUDIO_P0_BOUND = YES; SHARED_AI_LENS_BOUND = YES;
  SHARED_ACTION_DOCK_BOUND = YES; USER_REORDER_ACTIONS_REQUIRED = YES;
  USER_PIN_ACTIONS_REQUIRED = YES; AI_CANNOT_DISPLACE_PINNED_ACTIONS = YES;
  MOVABLE_LENS_REQUIRED = YES; RESIZABLE_LENS_REQUIRED = YES;
  REALTIME_SCROLL_TRANSLATION_REQUIRED = YES; READ_ALOUD_REQUIRED = YES;
  SHADOWING_REQUIRED = YES; NON_DESTRUCTIVE_SCREENSHOT_EDITING_REQUIRED =
  YES; STRUCTURED_ANNOTATION_GRAPH_REQUIRED = YES; NUMBER_MARKERS_REQUIRED
  = YES; ASK_AI_FROM_SCREENSHOT_REQUIRED = YES;
  TRANSLATOR_SCREENSHOT_INTEROP_REQUIRED = YES;
  NO_DUPLICATE_PERCEPTION_RUNTIME = YES; NO_DUPLICATE_AGENT_RUNTIME = YES.
- Ownership bindings (no module count/order change): S4-M10 shared semantic
  region/Focus Object/action adapter and Lens follow/selection semantic
  drivers where canonical ownership permits; S4-M11 provider/execution
  strategy routing (structured text vs OCR vs Vision, cached/local/cloud
  translation strategy, screenshot/Ask-AI strategy selection); S4-M12
  region/perception/action convergence, scroll/region freshness,
  stale-result drop, state-equivalent verification; Stage 5 reuses the
  canonical World/User/Experience/Intelligence owners (S5-M1 world/context;
  S5-M2 Personal Language Model / mastery state where canonical ownership
  permits; S5-M3 exposure/reflection/learning signals; S5-M7 PRIMARY
  Personal Translator language-intelligence owner; Smart Screenshot
  semantic understanding / Ask-AI binds to the appropriate existing Stage-5
  owner after repository/roadmap audit — no new Stage-5 module);
  S5-M10/M11 background learning / attention; S6-M4 PRIMARY Voice /
  Read-Aloud / Shadowing owner; S6-M7 PRIMARY shared foreground UX owner
  (AI Lens, AI Action Dock, Translation Lens, Island Translation Stream,
  Translation Card, Learning Dock, Smart Screenshot Studio, annotation
  editing, gesture/overlay interaction); S6-M8 integration/polish only.

### Personal Agent OS Roadmap Registry

All entries below are `ROADMAP_BOUND / NOT_IMPLEMENTED / NO_AUTHORITY`.
Registration neither starts implementation nor grants action authority.

| Feature | Canonical owner(s) |
| --- | --- |
| Personal Agent OS north star and principles | S6-M0 |
| Background First / Prepared Execution | S4-M0, S5-M10, S6-M1 |
| Foreground Lease | S4 observation primitives; S5-M10/M11 policy; S6-M1 UX |
| Mission/Goal/Project/Task identity; Plan as artifact | S5-M0/M1 |
| Personal World Model | S5-M1 with S5-M0/M2/M3 contracts |
| Personal Wiki | S5-M1 data; S6-M1 UX |
| Persistent Specialist Agents | S5-M10/M11 |
| Background/Idle Intelligence | S5-M10 |
| Execution Strategy Router | S4-M11 |
| Adaptive Intelligence Router and Intelligence Modes | S5-M11 |
| Agent Budget | S5-M11 |
| Progressive Capability Discovery | S5-M4/M11 |
| Opportunity Engine | S5-M10/M11; S6-M11 UX |
| Idea Object | S5-M1 semantics; S5-M10/M11 production; S6-M1/M11 UX |
| Attention Manager | S5-M11 |
| Reflection Engine | S5-M3 |
| Model Performance Memory | S5-M3 |
| Capability Benchmark Memory | S5-M3 |
| Live Artifact | S3 Artifact foundation; S6-M1 UX |
| Personal Agent Workspace | S6-M0/M1 |
| Unified Perception | S4-M0/M1/M2/M3/M12 |
| Delta Snapshot | S4-M3 with S4-M0 lineage/freshness |
| Semantic Wait | S4-M1/M12 |
| State-Equivalent Verifier gate | S4-M1/M12 |
| Live Voice / Barge-In / interruptible TTS | S6-M4 |
| Personal Translator (P0 product, feature.live_ai_translation_learning.v1) | S5-M7; S6-M7 UX; S6-M4 voice; S4-M0–M4 foundations; S5-M1/M2/M3; S5-M10/M11 |
| Live Media Interpreter (P0 Personal Translator mode; AudioSegment/MediaMoment/A-V fusion) | S5-M7 intelligence; S6-M4 audio/ASR/voice/shadowing; S6-M7 Adaptive Translation Island UX; S4-M10 adapters; S4-M11 provider strategy; S4-M12 cross-modal convergence/freshness |
| Smart Screenshot Studio (P0 product, feature.smart_screenshot_studio.v1) | S6-M7 UX; S4-M3 backend (FROZEN_PROVEN); S4-M0/M1/M2 foundations; Ask-AI binds to existing Stage-5 owners |
| PhoneHarness/ChatGPT/Siri Triple Entry | S6-M5/M9 |
| AI Lens Interaction System + AI Action Dock + Focus Object (shared foundation, AI_LENS_INTERACTION_SYSTEM_V1) | S6-M7 UX; S4-M10 adapters; S4-M11 strategy; consumers: Personal Translator + Smart Screenshot Studio + Ask AI/Extract/Inspect |

The existing Smart Screenshot entry remains authoritative and distinct. No
future registry entry is implemented merely by appearing in this table.

### Daily Experience Gate

The three P0 experiences cannot final-freeze from backend or Host tests alone.
Future acceptance requires `DAILY_EXPERIENCE_GATE = PASS` from real-device
daily-use evaluation covering English video, long and fast speech, accents,
noise, pause/resume and seek, orientation/app transitions, long sessions,
thermal and battery behavior, caption latency/stability, translation and
terminology quality, copy/replay/shadow workflows, learning continuity, and
Smart Screenshot learning flow. Exact latency thresholds require measured
device evidence.

## Weekly Radar Engineering Gates

- `TEXT_INPUT_REAL_DEVICE_COMPAT_GATE` (`S4-M4`, status `OPEN_DEFERRED`): close
  only after one fresh deterministic editable semantic target completes the
  full governed chain from legal operation through RiskController, binding,
  existing provider selection, device dispatch, text delivery, fresh
  post-dispatch observation, and semantic value verification. Until then,
  fail closed; no raw input, BKS, broadcast, ASCII, coordinate, or authority
  bypass is allowed.
- `BOOTSTRAP_2_2_1_COMPAT_GATE` (`S4` device gates): before future
  injection-dependent proof, record Bootstrap/RootHide/ElleKit versions and
  retest relevant SpringBoard/system injection, reinjection, frontmost, AX,
  input, preferences, and jailbreak-isolation behavior. Historical evidence
  does not prove a newer Bootstrap combination.
- `TRANSITION_DIVERGENCE_DIAGNOSTICS` (`S5-M3`): correlate pre-state,
  capability, binding/dispatch references, post-observation, verifier result,
  and failure signature to identify the first divergence and last verified
  state without creating another recovery runtime.
- `LOCAL_MODEL_BACKGROUND_RECOVERY_GATE` (`S6-M2`): future device proof must
  cover inference, backgrounding during decode, cancel/quiesce, foreground,
  backend health/rebuild, and a second successful inference.
- `STATE_EQUIVALENT_VERIFIER_GATE` (`S4-M1/M12`): future convergence requires
  `STATE_EQUIVALENT_RECOVERY_TEST = PASS`.
- `ROOTHIDE_PREFERENCE_REDIRECTION_FAULT_DOMAIN` (`S4-M5` and compatibility
  diagnostics): compare tweak injection off/on and inspect applicable
  preference/CF/cfprefsd/RunningBoard/FrontBoard evidence without attributing
  unproven current-version defects.
- `PACKAGE_ARCHITECTURE_GATE` (`S4-M8`): distinguish RootHide package
  architecture from ordinary rootless architecture before diagnosing loader
  or ElleKit failures.
- `MLC_LLM`: `DEFER / NO_ARCHITECTURE_CHANGE`; later implementation requires a
  fresh comparison and target-device proof.
- `P21_AI_NATIVE_FREEZE_GATE` (`S4-M6` and every later module Final
  Closeout/Freeze): `AI_NATIVE_INTEGRATION = PASS` required; no intelligence
  islands, no feature-specific AI/world/memory runtimes, no unjustified
  duplicate core systems. See the P21 section above.

## Reference Decision Registry

### Reference Harvest And Freshness

- Decision: `MANDATORY_PRE_IMPLEMENTATION_GATE`
- Status: `ACTIVE`
- Current-time refresh: `REQUIRED`
- Historical research alone: `INSUFFICIENT`

### Browser Use

- Decision: `REFERENCE_ONLY / ADAPT`
- Production dependency: `NO`
- Adapted concepts: `ObservationSnapshot`, Observation Epoch,
  `ObservedTargetRef`, `ActionCandidate`, `ActionCandidateSet`,
  `DecisionEnvelope`, `PreDispatchValidation`, Dynamic Legal Operation Set,
  `ExecutionLoopDetector`, `AvailableCapabilityView`, deterministic completion.

### Jev Constrained Decision References

- Decision: `REFERENCE_ONLY / ADAPT`
- Cloud hard dependency: `REJECTED`
- Adapted separation: `FAST_DECISION / SPECIALIST / GENERAL_LLM`
- Rejected: browser-runtime replacement, model `DONE` as semantic success,
  unverified multi-side-effect batching, DOM-only observation, or confidence
  replacing governance.

### MCP 2026 Protocol Direction

- Decision: `ADAPT AS EXTERNAL PROTOCOL REFERENCE`.
- Stateless core and explicit server-minted handles: `ADAPT`.
- PhoneHarness Runtime replacement: `REJECT`.
- MCP Tasks / `input_required` / MRTR: `ROADMAP_BOUND TO S4-M10 + S6-M12`;
  map to frozen PhoneHarness Async Task and intervention contracts rather than
  copying the external state machine.
- Tasks extension maturity: `IMPLEMENTATION_TIME_STATUS_CHECK_REQUIRED`.
- MCP Skills / Progressive Discovery proposals: `REFERENCE_CANDIDATE`.
- MCP Apps/artifact concepts: `UX_REFERENCE_ONLY`; native PhoneHarness
  Artifact contracts remain canonical.

### Semantic UI And Agent Product References

- Windows-MCP-style semantic UI, stale references, Semantic Wait, delta
  observation, and self-healing: `ADAPT` into Stage-4 owners without importing
  a second runtime or authority path.
- Muse-style Goal, Idea, Artifact, and persistent-agent concepts: `ADAPT/MERGE`
  into Stage-5/6 owners without a second Personal World Model.
- AgentTether-style transition diagnostics: `ADAPT` into S5-M3 without a
  second recovery runtime.

### Device And Local-Model References

- RootHide Bootstrap compatibility: `DEVICE_COMPATIBILITY_GATE`.
- ggml/llama.cpp/Metal background recovery reports: `S6-M2
  IMPLEMENTATION_GATE`; no assumption of automatic backend recovery.
- MLC-LLM: `DEFER`; no current architecture change or dependency.

Frozen invariants:

- `DecisionEnvelope != Authorization`
- `Confidence != Authorization`
- `TargetRef != Authorization`
- `Provider != Authorization`
- Dynamic legal operations cannot bypass Risk, binding, executor authority,
  freshness, or Semantic Verifier.

## Development Execution Policy

Default bounded work follows `AUDIT -> IMPLEMENT -> TEST -> EVIDENCE -> FINAL
REPORT`. Routine narration is omitted when a task requests final-only
reporting. Work stops for blockers, safety/scope/architecture/frozen-contract
conflicts, or required unavailable device evidence. Token conservation may not
reduce testing, verification, evidence quality, or fail-closed behavior.

## Historical Document Status

The following remain useful `HISTORICAL_REFERENCE` records but are not the
live roadmap:

- `docs/ROADMAP.md` below its canonical pointer;
- historical status sections in `docs/MASTER_HANDOFF.md`;
- `docs/NEXT_PHASE_ARCHITECTURE_REVIEW.md`;
- historical TEST, ADR, handoff, research, and frozen evidence records.

Primary entry documents must point here rather than duplicate this roadmap.

## Roadmap Lock

- A module may not start out of order without an explicit dependency-backed
  roadmap amendment.
- A roadmap amendment cannot rewrite frozen evidence.
- Stage 4 contains 13 modules, Stage 5 contains 12 modules, and Stage 6 contains
  15 modules unless an explicit architecture proposal proves the topology
  cannot express a required owner.
- No feature, provider, credential, confidence score, target reference, model,
  or decision envelope receives authorization by being listed here.
- Implementations must continue through the frozen PhoneHarness governance
  chain and applicable device evidence gates.
