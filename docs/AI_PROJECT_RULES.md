# PhoneHarness AI Project Rules

These rules apply to any capable AI coding agent working in this repository.
Repository evidence and fresh applicable test/device evidence override model
assumptions and conversation history.

## Product And Architecture Rules

- Goal is not Feature. Prefer reusable capabilities over one-off automation.
- Extend existing systems before proposing a second Planner, Router, Skill
  Registry, Capability Registry, Memory, Context, Executor, Ledger, or Verifier.
- Planner proposes; it does not authorize or execute.
- Skill describes governed capability; it is not security authority.
- Risk Controller owns authorization and risk decisions.
- Capability Binding selects only a registered trusted execution route.
- Adapter translates capability-specific typed inputs; it cannot self-authorize
  or self-verify.
- PlanExecutor alone owns action-capable execution.
- Observation reports reality; it is not action authority.
- Executor success does not prove semantic success.
- Verifier alone decides semantic success.
- No raw model text, free-form command, tool name, or arbitrary argument map may
  become executable.

Canonical action flow:

```text
Goal -> Context -> Planner -> Risk -> Capability Binding -> Adapter
-> PlanExecutor -> TEST-45 Ledger -> Observation -> Verifier -> Retry/Replan
```

## Evidence Rules

- No fresh applicable evidence means no PASS.
- Keep `STATIC_PASS`, `UNIT_PASS`, `INTEGRATION_PASS`, `NEGATIVE_PASS`,
  `SECURITY_PASS`, `REGRESSION_PASS`, `HOST_PASS`, `DEVICE_PASS`,
  `NOT_TESTED`, `BLOCKED`, `ENVIRONMENT_ISSUE`, and `FAIL` distinct.
- Never convert `NOT_TESTED`, `BLOCKED`, or `ENVIRONMENT_ISSUE` into PASS
  without new applicable evidence.
- Build, package audit, transfer, installation, host behavior, and observed
  device behavior are separate evidence classes.
- Do not replace an existing `DEVICE_PASS` route merely because a newer design
  looks cleaner. A material route change requires an appropriate new device
  regression Gate.
- State exactly what a device Gate proves and does not prove.

## TEST-51 / TEST-52 Frozen Boundary

- `TextField` does not prove `editable=true`.
- A non-secure element type does not prove `secure=false`.
- Derived visibility is not authorization-grade visibility.
- Focus on an ancestor, descendant, or unrelated element is not same-leaf
  semantic authorization.
- XCTest Observation Provider `DEVICE_PASS` does not authorize arbitrary
  `INPUT_TEXT` or `SUBMIT`.
- Memory, Context, Skill, Planner, Siri, Shortcut, App Intent, Scheduler, and UI
  may not bypass TEST-52.

## Recovery And Durability Rules

- TEST-45 `UNKNOWN_SIDE_EFFECT` prohibits blind retry or replay.
- TEST-46 recovery requires fresh observation, context update, replanning,
  reauthorization, and fresh Risk evaluation.
- Checkpoint is not authorization, current observation, or execution truth.
- Old confirmation does not authorize future execution.
- Stale observation cannot authorize resumed execution.
- Ledger and Verifier evidence outrank contradictory checkpoint metadata.
- Physical power-loss durability remains `NOT_TESTED`.
- Recovery/Durability is closed after TEST-59 unless concrete evidence reveals
  a new blocker.

## Knowledge And State Separation

- Knowledge: what the agent knows.
- Memory: privacy-safe summaries of what happened previously.
- Experience: validated evidence about what worked or was preferred.
- Active Context: what matters now for one owned task/workspace.
- Reference Resolver: what `this`, `he`, `that`, or `last one` refers to.
- Planner: what to propose next.
- Execution: governed work after authorization.

Do not merge these stores or treat historical data as current action authority.

## Privacy And Security

- Never intentionally persist or log passwords, OTPs, tokens, cookies, secure
  field values, or private credential material.
- Respect existing restrictions for raw screenshots, OCR/AX content, private
  documents, UI content, coordinates, vault material, raw MCP responses, and
  replayable action parameters.
- Payment, irreversible deletion, external communication, account-sensitive
  actions, and other high-risk work require confirmation under current Risk
  policy.
- Do not weaken RootHide, Bootstrap, AMFI, launchd, package-source, signing, or
  device security merely to make a Gate pass.

## Foundation Regression Gate

- A new candidate that breaks any historically `PASS` foundation capability is
  a `FOUNDATION_REGRESSION`; it does not invalidate the historical evidence.
- Before attributing it to USB, forwarding, RootHide, ElleKit, SpringBoard,
  preferences, or device state, compare `LAST_KNOWN_GOOD` and the candidate's
  source, linkage, package payload, and maintainer scripts.
- Every MCP candidate must pass the offline Foundation Gate before deployment:
  RootHide package/loader linkage; no rootful CydiaSubstrate linkage; unchanged
  SpringBoard filter; HTTP `/health` startup and token-auth contracts;
  `mcp-root` root/root mode `4755`; required exact runtime pin and revoked-pin
  absence; payload delta; maintainer scripts; root-owner package build; and
  the applicable Host regression. Invoke the command-line Gate with
  `--run-host-regression`; artifact checks alone cannot set `DEPLOY_READY`.
- For MCP, `packages/com.witchan.ios-mcp_1.2.2+ph1-13+roothide+debug-9+debug-1+debug_iphoneos-arm64e.deb`
  (SHA-256 `01732dddd3cbe177e3b02a358a86e87f8ec5c8f9bca1aff6ea629043709c815b`)
  is the immutable last-known-good `/health` baseline. Record a Foundation Diff
  and candidate SHA-256 with every MCP package report.
- Use only syntax recorded in `docs/DEVICE_TOOL_CAPABILITY_CONTRACT.md` for
  target-device packaging scripts. macOS command syntax is not device proof.
- After manual installation, stop feature testing unless package identity,
  RootHide linkage, respring, authenticated `/health`, and basic MCP health
  have all passed. A failed pre-flight is a Foundation Regression, not a reason
  to expand downstream feature diagnostics.
- Feature-isolated builds may not change package scheme, startup/bootstrap,
  maintainer scripts, preference semantics, or auth behavior unless explicitly
  in scope and independently gated.

## Engineering Method

Use:

```text
Borrow -> Evaluate -> Adapt -> Improve -> Validate
```

For major work:

```text
Requirement -> architecture/design -> failing test -> implementation
-> unit -> integration -> negative/fault injection -> security -> regression
-> fresh-context review -> device Gate where applicable
```

For failures:

```text
reproduce -> collect evidence -> identify root cause -> one hypothesis
-> minimal fix -> targeted retest -> regression
```

Quality is more important than token savings. Save tokens through concise task
prompts and targeted source reads, never by removing security analysis, failure
diagnosis, tests, or applicable device evidence.

## Worktree And Git Safety

The repository may contain important dirty and untracked project work.

Never automatically run or emulate:

- `git clean`
- `git reset --hard`
- `git restore .`
- `git checkout -- .`
- `git stash`
- deletion of untracked work

Inspect first and preserve unrelated or pre-existing changes. Do not stage,
commit, push, tag, release, or change branches without explicit user approval.

## Product Entry And Experience Boundaries

- Siri, App Intent, Shortcut, Action Button, Widget, voice, and app UI are
  clients of the same governed Runtime.
- They may submit a goal, display redacted task state, request approval, or
  request pause/cancel; they cannot call MCP/AX/Executor directly.
- Orb is a state/entry representation.
- Dynamic Island and Live Activity present task state, progress, or pending
  attention; they do not plan, authorize, schedule, or execute.
- Scheduler creates or reactivates governed intent through fresh Context,
  Planner, Risk, Executor, and Verifier cycles. It never replays old actions.
