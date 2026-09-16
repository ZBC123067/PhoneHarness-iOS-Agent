# ADR-045: Governed Capability Methods, Shortcuts, And App Intents

- Status: Accepted for TEST-40.3 contract implementation.
- Date: 2026-08-23
- Scope: Mac-hosted declarative governance.

## Context

The existing TEST-26 Capability Catalog describes what PhoneHarness knows it
can do. TEST-15/19 Skill Registry describes bounded reusable goal categories.
Neither should become a second executor, and neither should assume that UI
automation is the only way to act. Apple Shortcuts and App Intents are valuable
future execution and system-entry channels, but this project has not yet added
a Swift App Intent target or a safe Shortcut adapter.

## Decision

1. Reuse `CapabilityCatalog` as the capability authority and add a separate
   metadata-only `CapabilityMethodRegistry` for multiple methods per
   capability.
2. Treat `apple_shortcut` and `app_intent` as method types, not as Skills.
   Skills remain goal-category contracts; a method only describes a possible
   later execution channel.
3. Provide `ShortcutRegistry` and `AppIntentRegistry` as validation adapters
   that translate a safe descriptor into a Capability Method declaration. They
   neither inspect, create, import, run, nor serialize shortcut/intent payloads.
4. Add `SkillGovernanceCatalog` as a review companion, not a runtime Skill
   Registry. It cannot select a Skill, alter the existing SkillRegistry, or
   execute an action.
5. Keep every action on the existing `Planner -> Risk Controller -> Plan
   Executor -> MCP -> Verifier` route. Future Shortcut/App Intent adapters must
   enter through the same policy route and need separate approval.
6. Use evidence-gated lifecycle state. An external candidate cannot become
   active in TEST-40.3 because source analysis, sandbox testing, user approval,
   and a later adapter are intentionally out of scope.

## Consequences

### Positive

- Method reliability can favour Apple-native system interfaces before UI
  automation without hard-coding an app, bundle identifier, or coordinate.
- A Shortcut/App Intent implementation can be added later without changing
  Planner, Risk, Executor, or Verifier ownership.
- User-taught and external Skill candidates are visible/auditable without
  becoming device automation merely because they were discovered.

### Costs

- There is deliberately no operational Shortcut discovery, Shortcut creation,
  Siri, Spotlight, Widget, Action Button, or App Intent feature in TEST-40.3.
- A future iOS target must supply platform permission/availability evidence
  before any Apple-native method becomes active.

## External Reference Decision

Apple documents App Intents as the system integration model for supported
experiences such as Siri, Shortcuts, Spotlight, widgets, and related system
surfaces. Apple documents App Shortcuts as preconfigured App Intent phrases.
These are architecture references only. No Apple SDK code, external framework,
or third-party Shortcut is adopted in TEST-40.3; therefore no license,
RootHide, or existing device-test boundary changes are introduced.

## Rejected Alternatives

1. Treat every Shortcut as a Skill: rejected because it conflates a user goal
   contract with one execution channel.
2. Allow Planner or Capability Catalog to invoke an App Intent/Shortcut:
   rejected because it bypasses existing Risk/Executor/Verifier ownership.
3. Import third-party Skills or community Shortcuts automatically: rejected
   because it creates unreviewed code/permission supply-chain risk.
4. Build Swift/iOS entry points now: rejected because TEST-40.3 is a governed
   Mac-side foundation; the iOS experience layer needs a separate product and
   real-device approval.

